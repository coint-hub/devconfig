import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from devconfig.bin import cli
from devconfig.bin.cli import app, find_root

runner = CliRunner()


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
    @pytest.fixture
    def allowed(self, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
        calls: list[Path] = []
        monkeypatch.setattr(cli, "_direnv_allow", calls.append)
        return calls

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

    @pytest.mark.usefixtures("allowed")
    def test_init_from_module_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_project(tmp_path, ["awesome-app"])
        monkeypatch.chdir(tmp_path / "awesome-app")

        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0, result.output
        assert (tmp_path / ".envrc").read_text() == "use nix\n"
        assert (tmp_path / "awesome-app" / ".envrc").read_text() == "source_up\n"

    @pytest.mark.usefixtures("allowed")
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
