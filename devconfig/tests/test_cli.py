import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter
from typer.testing import CliRunner

from devconfig.bin import cli
from devconfig.bin.cli import app, find_root

runner = CliRunner()

_ports_adapter = TypeAdapter(dict[str, int])


def _read_ports(path: Path) -> dict[str, int]:
    return _ports_adapter.validate_json(path.read_text())


@pytest.fixture(autouse=True)
def allowed(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    calls: list[Path] = []
    monkeypatch.setattr(cli, "_direnv_allow", calls.append)
    return calls


@pytest.fixture(autouse=True)
def jar_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "jar.json"
    monkeypatch.setenv("DEVCONFIG_JAR", str(path))
    return path


@pytest.fixture(autouse=True)
def git_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    def ignored(_: Path) -> bool:
        return True

    monkeypatch.setattr(cli, "_git_ignored", ignored)


def test_no_arguments_shows_help() -> None:
    result = runner.invoke(app, [])

    assert "Usage" in result.output
    assert "init" in result.output


def _make_project(root: Path, modules: list[str]) -> None:
    (root / ".git").mkdir()
    (root / "devconfig.json").write_text(
        json.dumps(
            {
                "project_name": "awesome-project",
                "modules": [{"name": name} for name in modules],
            }
        )
    )
    for name in modules:
        (root / name).mkdir()


WAS_MODULE: dict[str, object] = {
    "name": "awesome-was",
    "services": [{"name": "api", "type": "web"}],
    "docker-compose": {"services": [{"name": "db", "type": "postgresql"}]},
}


def _make_worktree(
    container: Path, work_name: str, modules: list[dict[str, object]]
) -> Path:
    root = container / work_name
    root.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "devconfig.json").write_text(
        json.dumps({"project_name": "awesome-project", "modules": modules})
    )
    for module in modules:
        name = module["name"]
        assert isinstance(name, str)
        module_dir = root / name
        module_dir.mkdir()
        if "docker-compose" in module:
            (module_dir / "compose.yaml").touch()
    return root


class TestFindRoot:
    def test_finds_root_from_nested_directory(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        (tmp_path / "devconfig.json").touch()
        nested = tmp_path / "app" / "src"
        nested.mkdir(parents=True)

        assert find_root(nested) == tmp_path

    def test_finds_root_when_git_is_a_file(self, tmp_path: Path) -> None:
        (tmp_path / ".git").write_text("gitdir: /somewhere/else\n")
        (tmp_path / "devconfig.json").touch()

        assert find_root(tmp_path) == tmp_path

    def test_git_without_devconfig_json_raises(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()

        with pytest.raises(AssertionError, match="no devconfig.json"):
            find_root(tmp_path)

    def test_devconfig_json_without_git_raises(self, tmp_path: Path) -> None:
        (tmp_path / "devconfig.json").touch()

        with pytest.raises(AssertionError, match="no .git"):
            find_root(tmp_path)

    def test_no_markers_raises(self, tmp_path: Path) -> None:
        with pytest.raises(AssertionError, match="not inside a devconfig project"):
            find_root(tmp_path)

    def test_stops_at_nearest_marker(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        (tmp_path / "devconfig.json").touch()
        inner = tmp_path / "vendored"
        inner.mkdir()
        (inner / ".git").mkdir()

        with pytest.raises(AssertionError, match="no devconfig.json"):
            find_root(inner)


class TestInit:
    def test_fresh_init_writes_envrc_and_allows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, allowed: list[Path]
    ) -> None:
        _make_project(tmp_path, ["awesome-app", "awesome-api"])
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0, result.output
        assert (tmp_path / ".envrc").read_text() == "use nix\n"
        assert (tmp_path / "awesome-app" / ".envrc").read_text() == "source_up\n"
        assert (tmp_path / "awesome-api" / ".envrc").read_text() == "source_up\n"
        assert allowed == [
            tmp_path,
            tmp_path / "awesome-app",
            tmp_path / "awesome-api",
        ]

    def test_init_from_module_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_project(tmp_path, ["awesome-app"])
        monkeypatch.chdir(tmp_path / "awesome-app")

        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0, result.output
        assert (tmp_path / ".envrc").read_text() == "use nix\n"
        assert (tmp_path / "awesome-app" / ".envrc").read_text() == "source_up\n"

    def test_rerun_is_idempotent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_project(tmp_path, ["awesome-app"])
        monkeypatch.chdir(tmp_path)
        assert runner.invoke(app, ["init"]).exit_code == 0

        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0, result.output
        assert (tmp_path / ".envrc").read_text() == "use nix\n"
        assert (tmp_path / "awesome-app" / ".envrc").read_text() == "source_up\n"

    def test_conflicting_root_envrc_aborts_before_writing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, allowed: list[Path]
    ) -> None:
        _make_project(tmp_path, ["awesome-app"])
        (tmp_path / ".envrc").write_text("use flake\nexport QUIRK=1\n")
        monkeypatch.chdir(tmp_path)

        with pytest.raises(AssertionError, match="use flake"):
            cli.init()

        assert not (tmp_path / "awesome-app" / ".envrc").exists()
        assert allowed == []

    def test_conflicting_module_envrc_aborts_before_writing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, allowed: list[Path]
    ) -> None:
        _make_project(tmp_path, ["awesome-app"])
        (tmp_path / "awesome-app" / ".envrc").write_text("source_up\nexport QUIRK=1\n")
        monkeypatch.chdir(tmp_path)

        with pytest.raises(AssertionError, match="QUIRK"):
            cli.init()

        assert not (tmp_path / ".envrc").exists()
        assert allowed == []

    def test_missing_module_directory_aborts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, allowed: list[Path]
    ) -> None:
        _make_project(tmp_path, ["awesome-app"])
        (tmp_path / "awesome-app").rmdir()
        monkeypatch.chdir(tmp_path)

        with pytest.raises(AssertionError, match="awesome-app"):
            cli.init()

        assert not (tmp_path / ".envrc").exists()
        assert allowed == []


class TestInitPorts:
    def test_writes_ports_file_to_worktree_container(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        container = tmp_path / "awesome.worktree"
        root = _make_worktree(container, "main", [WAS_MODULE])
        monkeypatch.chdir(root)

        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0, result.output
        data = _read_ports(container / "devconfig-main.json")
        assert data == {
            "AWESOME_PROJECT_AWESOME_WAS_API_PORT": 30000,
            "AWESOME_PROJECT_AWESOME_WAS_DB_PORT": 30001,
        }

    def test_rerun_yields_same_ports(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        container = tmp_path / "awesome.worktree"
        root = _make_worktree(container, "main", [WAS_MODULE])
        monkeypatch.chdir(root)
        assert runner.invoke(app, ["init"]).exit_code == 0
        first = _read_ports(container / "devconfig-main.json")

        assert runner.invoke(app, ["init"]).exit_code == 0

        second = _read_ports(container / "devconfig-main.json")
        assert first == second

    def test_worktrees_get_distinct_ports(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        container = tmp_path / "awesome.worktree"
        root_main = _make_worktree(container, "main", [WAS_MODULE])
        root_feature = _make_worktree(container, "feature", [WAS_MODULE])
        monkeypatch.chdir(root_main)
        assert runner.invoke(app, ["init"]).exit_code == 0
        monkeypatch.chdir(root_feature)

        assert runner.invoke(app, ["init"]).exit_code == 0

        main_ports = _read_ports(container / "devconfig-main.json")
        feature_ports = _read_ports(container / "devconfig-feature.json")
        assert set(main_ports.values()).isdisjoint(feature_ports.values())

    def test_module_without_services_yields_empty_ports_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        container = tmp_path / "awesome.worktree"
        root = _make_worktree(container, "main", [{"name": "awesome-app"}])
        monkeypatch.chdir(root)

        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0, result.output
        assert _read_ports(container / "devconfig-main.json") == {}

    def test_duplicate_service_names_abort_before_writing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, allowed: list[Path]
    ) -> None:
        container = tmp_path / "awesome.worktree"
        module: dict[str, object] = {
            "name": "awesome-was",
            "services": [{"name": "db", "type": "web"}],
            "docker-compose": {"services": [{"name": "db", "type": "postgresql"}]},
        }
        root = _make_worktree(container, "main", [module])
        monkeypatch.chdir(root)

        with pytest.raises(AssertionError, match="duplicate environment variable"):
            cli.init()

        assert not (root / ".envrc").exists()
        assert not (container / "devconfig-main.json").exists()
        assert allowed == []


class TestCompose:
    def test_writes_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        container = tmp_path / "awesome.worktree"
        root = _make_worktree(container, "main", [WAS_MODULE])
        monkeypatch.chdir(root)

        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0, result.output
        override = root / "awesome-was" / "compose.override.yaml"
        assert override.read_text() == (
            "# devconfig\n"
            "name: awesome-project-awesome-was-main\n"
            "services:\n"
            "  db:\n"
            "    ports: !override\n"
            '      - "30001:5432"\n'
        )

    def test_missing_compose_yaml_aborts_before_writing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, allowed: list[Path]
    ) -> None:
        container = tmp_path / "awesome.worktree"
        root = _make_worktree(container, "main", [WAS_MODULE])
        (root / "awesome-was" / "compose.yaml").unlink()
        monkeypatch.chdir(root)

        with pytest.raises(AssertionError, match="compose file not found"):
            cli.init()

        assert not (root / ".envrc").exists()
        assert not (container / "devconfig-main.json").exists()
        assert allowed == []

    def test_not_git_ignored_aborts_before_writing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, allowed: list[Path]
    ) -> None:
        container = tmp_path / "awesome.worktree"
        root = _make_worktree(container, "main", [WAS_MODULE])
        monkeypatch.chdir(root)

        def not_ignored(_: Path) -> bool:
            return False

        monkeypatch.setattr(cli, "_git_ignored", not_ignored)

        with pytest.raises(AssertionError, match="not ignored by git"):
            cli.init()

        assert not (root / ".envrc").exists()
        assert not (container / "devconfig-main.json").exists()
        assert not (root / "awesome-was" / "compose.override.yaml").exists()
        assert allowed == []

    def test_foreign_override_aborts_before_writing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, allowed: list[Path]
    ) -> None:
        container = tmp_path / "awesome.worktree"
        root = _make_worktree(container, "main", [WAS_MODULE])
        override = root / "awesome-was" / "compose.override.yaml"
        override.write_text("services:\n  db:\n    ports: []\n")
        monkeypatch.chdir(root)

        with pytest.raises(AssertionError, match="marker"):
            cli.init()

        assert not (root / ".envrc").exists()
        assert not (container / "devconfig-main.json").exists()
        assert override.read_text() == "services:\n  db:\n    ports: []\n"
        assert allowed == []

    def test_rerun_over_own_override_succeeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        container = tmp_path / "awesome.worktree"
        root = _make_worktree(container, "main", [WAS_MODULE])
        monkeypatch.chdir(root)
        assert runner.invoke(app, ["init"]).exit_code == 0
        override = root / "awesome-was" / "compose.override.yaml"
        first = override.read_text()

        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0, result.output
        assert override.read_text() == first
