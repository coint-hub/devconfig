import json
import os
import subprocess
import tomllib
from enum import StrEnum, auto, unique
from pathlib import Path

import typer
from pydantic import BaseModel, Field

from devconfig.model import Jar

app = typer.Typer(no_args_is_help=True)

DEVCONFIG_FILE = "devconfig.toml"
ROOT_ENVRC = "use nix"
MODULE_ENVRC = "source_up"
COMPOSE_FILE = "compose.yaml"
COMPOSE_OVERRIDE_FILE = "compose.override.yaml"
VITE_SH_FILE = "vite.sh"
VITE_SH_SHEBANG = "#!/bin/sh"
GENERATED_MARKER = "# devconfig"


@unique
class ModuleServiceType(StrEnum):
    WEB = auto()
    FLASK = auto()
    VITE = auto()


@unique
class ComposeServiceType(StrEnum):
    POSTGRESQL = auto()

    @property
    def container_port(self) -> int:
        match self:
            case ComposeServiceType.POSTGRESQL:
                return 5432


class ModuleService(BaseModel):
    name: str
    type: ModuleServiceType | None = None


class ComposeService(BaseModel):
    name: str
    type: ComposeServiceType


class DockerCompose(BaseModel):
    services: list[ComposeService]


class DevConfigModule(BaseModel):
    name: str
    services: list[ModuleService] = []
    docker_compose: DockerCompose | None = Field(default=None, alias="docker-compose")


class DevConfig(BaseModel):
    project_name: str
    modules: list[DevConfigModule]

    @staticmethod
    def load(path: Path) -> DevConfig:
        with open(path, "rb") as f:
            return DevConfig.model_validate(tomllib.load(f))


def find_root(start: Path) -> Path:
    """Climb from start to the nearest directory holding .git or devconfig.toml.

    Both markers must be present there; .git may be a file (git worktree).
    """
    for directory in (start, *start.parents):
        has_git = (directory / ".git").exists()
        has_devconfig = (directory / DEVCONFIG_FILE).exists()
        if has_git and has_devconfig:
            return directory
        assert not (directory / "devconfig.json").exists(), (
            f"found legacy devconfig.json at {directory}: "
            f"convert it to {DEVCONFIG_FILE}"
        )
        assert not has_git, f"found .git at {directory}, but no {DEVCONFIG_FILE}"
        assert not has_devconfig, f"found {DEVCONFIG_FILE} at {directory}, but no .git"
    raise AssertionError(
        f"not inside a devconfig project: no .git / {DEVCONFIG_FILE} found from {start}"
    )


@app.callback()
def main() -> None:
    """Configure dev environments for monorepo projects."""


@app.command()
def init() -> None:
    """Set up direnv, assign ports, and write docker-compose overrides."""
    root = find_root(Path.cwd())
    config = DevConfig.load(root / DEVCONFIG_FILE)
    jar_path = _jar_path()

    targets = [(root, ROOT_ENVRC)]
    for module in config.modules:
        module_dir = root / module.name
        assert module_dir.is_dir(), f"module directory not found: {module_dir}"
        targets.append((module_dir, MODULE_ENVRC))

    # Validate every target before writing anything, so a conflict aborts cleanly.
    for directory, line in targets:
        envrc = directory / ".envrc"
        if not envrc.exists():
            continue
        content = envrc.read_text()
        assert content.strip() == line, (
            f"refusing to touch {envrc}: expected {line!r}, found:\n{content}"
        )
    for module in config.modules:
        _validate_compose(root, module)
        _validate_vite(root, module)

    jar = Jar.load(jar_path)
    values = _assign_values(config, work_name=root.name, jar=jar)

    for directory, line in targets:
        envrc = directory / ".envrc"
        if envrc.exists():
            typer.echo(f"{envrc}: ok")
        else:
            envrc.write_text(f"{line}\n")
            typer.echo(f"{envrc}: wrote {line!r}")
        _direnv_allow(directory)

    values_path = root.parent / f"devconfig-{root.name}.json"
    with open(values_path, "w") as f:
        json.dump(values, f, indent=2, sort_keys=True, ensure_ascii=False)
    typer.echo(f"{values_path}: wrote {len(values)} values")

    for module in config.modules:
        _write_compose_override(root, config, module, values)
        _write_vite_sh(root, config, module, values)

    jar.save(jar_path)


def _validate_compose(root: Path, module: DevConfigModule) -> None:
    if module.docker_compose is None:
        return
    module_dir = root / module.name
    compose = module_dir / COMPOSE_FILE
    assert compose.is_file(), f"compose file not found: {compose}"
    override = module_dir / COMPOSE_OVERRIDE_FILE
    assert _git_ignored(override), (
        f"refusing to write {override}: not ignored by git, add it to .gitignore"
    )
    if override.exists():
        content = override.read_text()
        assert content.startswith(GENERATED_MARKER), (
            f"refusing to touch {override}: "
            f"missing {GENERATED_MARKER!r} marker, found:\n{content}"
        )


def _vite_services(module: DevConfigModule) -> list[ModuleService]:
    return [s for s in module.services if s.type is ModuleServiceType.VITE]


def _validate_vite(root: Path, module: DevConfigModule) -> None:
    services = _vite_services(module)
    if not services:
        return
    assert len(services) == 1, (
        f"at most one vite service per module: {module.name=}, "
        f"found {[s.name for s in services]}"
    )
    vite_sh = root / module.name / VITE_SH_FILE
    assert _git_ignored(vite_sh), (
        f"refusing to write {vite_sh}: not ignored by git, add it to .gitignore"
    )
    if vite_sh.exists():
        content = vite_sh.read_text()
        # Early versions wrote the marker without a shebang; accept both.
        body = content.removeprefix(f"{VITE_SH_SHEBANG}\n")
        assert body.startswith(GENERATED_MARKER), (
            f"refusing to touch {vite_sh}: "
            f"missing {GENERATED_MARKER!r} marker, found:\n{content}"
        )


def _assign_values(
    config: DevConfig, *, work_name: str, jar: Jar
) -> dict[str, int | bool | str]:
    values: dict[str, int | bool | str] = {}

    def put(key: str, value: int | bool | str) -> None:
        assert key not in values, f"duplicate environment variable: {key=}"
        values[key] = value

    for module in config.modules:
        compose_services = (
            [] if module.docker_compose is None else module.docker_compose.services
        )
        for service in [*module.services, *compose_services]:
            key = _key(config.project_name, module.name, service.name, "port")
            port = jar.get_or_assign_port(
                config_name=config.project_name, work_name=work_name, key=key
            )
            put(key, port)
        for service in module.services:
            if service.type is ModuleServiceType.FLASK:
                put(_key(config.project_name, module.name, service.name, "debug"), True)
                secret_key = _key(
                    config.project_name, module.name, service.name, "secret_key"
                )
                secret = jar.get_or_assign_secret(
                    config_name=config.project_name, work_name=work_name, key=secret_key
                )
                put(secret_key, secret)
    return values


def _write_compose_override(
    root: Path,
    config: DevConfig,
    module: DevConfigModule,
    values: dict[str, int | bool | str],
) -> None:
    if module.docker_compose is None:
        return
    # YAML is built by hand because the leading marker comment must survive;
    # switch to a YAML library once one that can emit comments turns up.
    lines = [
        GENERATED_MARKER,
        f"name: {config.project_name}-{module.name}-{root.name}",
        "services:",
    ]
    for service in module.docker_compose.services:
        port = values[_key(config.project_name, module.name, service.name, "port")]
        lines += [
            f"  {service.name}:",
            # !override replaces the base file's ports; a plain merge appends.
            "    ports: !override",
            f'      - "{port}:{service.type.container_port}"',
        ]
    override = root / module.name / COMPOSE_OVERRIDE_FILE
    override.write_text("\n".join(lines) + "\n")
    typer.echo(f"{override}: wrote override")


def _write_vite_sh(
    root: Path,
    config: DevConfig,
    module: DevConfigModule,
    values: dict[str, int | bool | str],
) -> None:
    services = _vite_services(module)
    if not services:
        return
    (service,) = services
    port = values[_key(config.project_name, module.name, service.name, "port")]
    vite_sh = root / module.name / VITE_SH_FILE
    lines = [
        VITE_SH_SHEBANG,
        GENERATED_MARKER,
        f'exec pnpm exec vite --port={port} --host="0.0.0.0" "$@"',
    ]
    vite_sh.write_text("\n".join(lines) + "\n")
    vite_sh.chmod(0o755)
    typer.echo(f"{vite_sh}: wrote launch script, port {port}")


def _jar_path() -> Path:
    jar = os.environ.get("DEVCONFIG_JAR")
    assert jar, "DEVCONFIG_JAR is not set"
    return Path(jar).resolve()


def _git_ignored(path: Path) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(path)], cwd=path.parent, check=False
    )
    return result.returncode == 0


def _direnv_allow(path: Path) -> None:
    subprocess.run(["direnv", "allow", str(path)], check=True)


def _key(*names: str) -> str:
    return "_".join(names).replace("-", "_").upper()


if __name__ == "__main__":
    app()
