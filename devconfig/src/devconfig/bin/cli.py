import json
import os
import subprocess
from enum import StrEnum, auto, unique
from pathlib import Path

import typer
from pydantic import BaseModel, Field

from devconfig.model import Jar

app = typer.Typer(no_args_is_help=True)

ROOT_ENVRC = "use nix"
MODULE_ENVRC = "source_up"
COMPOSE_FILE = "compose.yaml"
COMPOSE_OVERRIDE_FILE = "compose.override.yaml"
COMPOSE_OVERRIDE_MARKER = "# devconfig"


@unique
class ModuleServiceType(StrEnum):
    WEB = auto()


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
    def load(json_path: Path) -> DevConfig:
        with open(json_path, "r") as f:
            return DevConfig.model_validate(json.load(f))


def find_root(start: Path) -> Path:
    """Climb from start to the nearest directory holding .git or devconfig.json.

    Both markers must be present there; .git may be a file (git worktree).
    """
    for directory in (start, *start.parents):
        has_git = (directory / ".git").exists()
        has_devconfig = (directory / "devconfig.json").exists()
        if has_git and has_devconfig:
            return directory
        assert not has_git, f"found .git at {directory}, but no devconfig.json"
        assert not has_devconfig, f"found devconfig.json at {directory}, but no .git"
    raise AssertionError(
        f"not inside a devconfig project: no .git / devconfig.json found from {start}"
    )


@app.callback()
def main() -> None:
    """Configure dev environments for monorepo projects."""


@app.command()
def init() -> None:
    """Set up direnv, assign ports, and write docker-compose overrides."""
    root = find_root(Path.cwd())
    config = DevConfig.load(root / "devconfig.json")
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

    jar = Jar.load(jar_path)
    ports = _assign_ports(config, work_name=root.name, jar=jar)

    for directory, line in targets:
        envrc = directory / ".envrc"
        if envrc.exists():
            typer.echo(f"{envrc}: ok")
        else:
            envrc.write_text(f"{line}\n")
            typer.echo(f"{envrc}: wrote {line!r}")
        _direnv_allow(directory)

    ports_path = root.parent / f"devconfig-{root.name}.json"
    with open(ports_path, "w") as f:
        json.dump(ports, f, indent=2, sort_keys=True, ensure_ascii=False)
    typer.echo(f"{ports_path}: wrote {len(ports)} ports")

    for module in config.modules:
        _write_compose_override(root, config, module, ports)

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
        assert content.startswith(COMPOSE_OVERRIDE_MARKER), (
            f"refusing to touch {override}: "
            f"missing {COMPOSE_OVERRIDE_MARKER!r} marker, found:\n{content}"
        )


def _assign_ports(config: DevConfig, *, work_name: str, jar: Jar) -> dict[str, int]:
    ports: dict[str, int] = {}
    for module in config.modules:
        compose_services = (
            [] if module.docker_compose is None else module.docker_compose.services
        )
        for service in [*module.services, *compose_services]:
            key = _key(config.project_name, module.name, service.name, "port")
            assert key not in ports, f"duplicate environment variable: {key=}"
            ports[key] = jar.get_or_assign_port(
                config_name=config.project_name, work_name=work_name, key=key
            )
    return ports


def _write_compose_override(
    root: Path, config: DevConfig, module: DevConfigModule, ports: dict[str, int]
) -> None:
    if module.docker_compose is None:
        return
    # YAML is built by hand because the leading marker comment must survive;
    # switch to a YAML library once one that can emit comments turns up.
    lines = [
        COMPOSE_OVERRIDE_MARKER,
        f"name: {config.project_name}-{module.name}-{root.name}",
        "services:",
    ]
    for service in module.docker_compose.services:
        port = ports[_key(config.project_name, module.name, service.name, "port")]
        lines += [
            f"  {service.name}:",
            # !override replaces the base file's ports; a plain merge appends.
            "    ports: !override",
            f'      - "{port}:{service.type.container_port}"',
        ]
    override = root / module.name / COMPOSE_OVERRIDE_FILE
    override.write_text("\n".join(lines) + "\n")
    typer.echo(f"{override}: wrote override")


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
