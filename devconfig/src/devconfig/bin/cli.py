import json
import subprocess
from pathlib import Path

import typer
from pydantic import BaseModel

app = typer.Typer(no_args_is_help=True)

ROOT_ENVRC = "use nix"
MODULE_ENVRC = "source_up"


class DevConfigModule(BaseModel):
    name: str


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
    """Set up direnv: 'use nix' at the project root, 'source_up' in each module."""
    root = find_root(Path.cwd())
    config = DevConfig.load(root / "devconfig.json")

    targets = [(root, ROOT_ENVRC)]
    for module in config.modules:
        module_dir = root / module.name
        assert module_dir.is_dir(), f"module directory not found: {module_dir}"
        targets.append((module_dir, MODULE_ENVRC))

    # Validate every .envrc before writing anything, so a conflict aborts cleanly.
    for directory, line in targets:
        envrc = directory / ".envrc"
        if not envrc.exists():
            continue
        content = envrc.read_text()
        assert content.strip() == line, (
            f"refusing to touch {envrc}: expected {line!r}, found:\n{content}"
        )

    for directory, line in targets:
        envrc = directory / ".envrc"
        if envrc.exists():
            typer.echo(f"{envrc}: ok")
        else:
            envrc.write_text(f"{line}\n")
            typer.echo(f"{envrc}: wrote {line!r}")
        _direnv_allow(directory)


def _direnv_allow(path: Path) -> None:
    subprocess.run(["direnv", "allow", str(path)], check=True)


if __name__ == "__main__":
    app()
