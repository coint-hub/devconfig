import json
from pathlib import Path

import pytest

from devconfig.bin.main import (
    Config,
    DevConfig,
    Jar,
    _key,  # pyright: ignore[reportPrivateUsage]
    main,
    write_envrc,
)
from devconfig.model import DevConfigModel


def test_key_joins_and_uppercases() -> None:
    assert _key("demo", "api", "port") == "DEMO_API_PORT"
    assert _key("demo") == "DEMO"


class TestJar:
    def test_assigns_ports_sequentially_from_30000(self) -> None:
        jar = Jar()

        first = jar.get_or_assign_port(config_name="demo", work_name="main", key="A")
        second = jar.get_or_assign_port(config_name="demo", work_name="main", key="B")

        assert first == 30000
        assert second == 30001

    def test_same_key_returns_same_port(self) -> None:
        jar = Jar()

        first = jar.get_or_assign_port(config_name="demo", work_name="main", key="A")
        again = jar.get_or_assign_port(config_name="demo", work_name="main", key="A")

        assert again == first

    def test_different_work_name_gets_different_port(self) -> None:
        jar = Jar()

        main_port = jar.get_or_assign_port(
            config_name="demo", work_name="main", key="A"
        )
        feature_port = jar.get_or_assign_port(
            config_name="demo", work_name="feature", key="A"
        )

        assert main_port != feature_port

    def test_load_missing_file_returns_empty_jar(self, tmp_path: Path) -> None:
        jar = Jar.load(tmp_path / "missing.json")

        assert jar.ports == {}

    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        json_path = tmp_path / "jar.json"
        jar = Jar(ports={"demo:main:DEMO_API_PORT": 30000})

        jar.save(json_path)
        loaded = Jar.load(json_path)

        assert loaded == jar

    def test_save_writes_sorted_indented_json(self, tmp_path: Path) -> None:
        json_path = tmp_path / "jar.json"
        jar = Jar(ports={"b": 30001, "a": 30000})

        jar.save(json_path)

        expected = json.dumps(
            {"ports": {"a": 30000, "b": 30001}}, indent=2, sort_keys=True
        )
        assert json_path.read_text() == expected


def _devconfig(services: list[dict[str, str]], work_name: str = "main") -> DevConfig:
    model = DevConfigModel.model_validate({"name": "demo", "services": services})
    return DevConfig(model, work_name)


class TestDevConfigServiceRender:
    def test_untyped_service_renders_port_only(self) -> None:
        devconfig = _devconfig([{"name": "db"}])

        values = devconfig.services[0].render(jar=Jar())

        assert values == [("DEMO_DB_PORT", "30000")]

    def test_web_service_renders_port_and_url(self) -> None:
        devconfig = _devconfig([{"name": "front", "type": "web"}])

        values = devconfig.services[0].render(jar=Jar())

        assert values == [
            ("DEMO_FRONT_PORT", "30000"),
            ("DEMO_FRONT_URL", "http://127.0.0.1:30000"),
        ]

    def test_spring_service_writes_yaml_and_renders_url(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "main" / "resources").mkdir(parents=True)
        devconfig = _devconfig(
            [{"name": "api", "type": "spring", "path": str(tmp_path)}]
        )

        values = devconfig.services[0].render(jar=Jar())

        assert values == [
            ("DEMO_API_PORT", "30000"),
            ("DEMO_API_URL", "http://127.0.0.1:30000"),
        ]
        yaml_path = tmp_path / "src" / "main" / "resources" / "application-default.yml"
        assert yaml_path.read_text() == "server.port: 30000\n"

    def test_spring_service_without_path_raises(self) -> None:
        devconfig = _devconfig([{"name": "api", "type": "spring"}])

        with pytest.raises(AssertionError):
            devconfig.services[0].render(jar=Jar())


class TestDevConfigRender:
    def test_renders_work_name_and_all_services(self) -> None:
        devconfig = _devconfig(
            [{"name": "front", "type": "web"}, {"name": "db"}], work_name="feature"
        )

        values = devconfig.render(Jar())

        assert values == {
            "DEMO_WORK_NAME": "feature",
            "DEMO_FRONT_PORT": "30000",
            "DEMO_FRONT_URL": "http://127.0.0.1:30000",
            "DEMO_DB_PORT": "30001",
        }

    def test_duplicate_service_name_raises(self) -> None:
        devconfig = _devconfig([{"name": "db"}, {"name": "db"}])

        with pytest.raises(AssertionError):
            devconfig.render(Jar())

    def test_rerender_with_same_jar_keeps_ports(self) -> None:
        jar = Jar()
        devconfig = _devconfig([{"name": "front", "type": "web"}, {"name": "db"}])

        first = devconfig.render(jar)
        second = devconfig.render(jar)

        assert second == first


def test_write_envrc_writes_export_lines(tmp_path: Path) -> None:
    envrc_path = tmp_path / ".envrc.devconfig"

    write_envrc(envrc_path, {"DEMO_DB_PORT": "30000", "DEMO_WORK_NAME": "main"})

    assert envrc_path.read_text() == (
        'export DEMO_DB_PORT="30000"\nexport DEMO_WORK_NAME="main"\n'
    )


class TestMain:
    @pytest.fixture
    def work_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setattr(Config, "work_path", tmp_path)
        monkeypatch.setattr(Config, "envrc_path", tmp_path / ".envrc.devconfig")
        monkeypatch.setattr(Config, "devconfig_path", tmp_path / "devconfig.json")
        monkeypatch.setattr(Config, "jar_path", tmp_path / "jar.json")

        Config.devconfig_path.write_text(
            json.dumps(
                {
                    "name": "demo",
                    "services": [{"name": "front", "type": "web"}, {"name": "db"}],
                }
            )
        )
        return tmp_path

    def test_writes_envrc_and_jar(self, work_path: Path) -> None:
        main()

        work_name = work_path.name
        assert (work_path / ".envrc.devconfig").read_text() == (
            f'export DEMO_WORK_NAME="{work_name}"\n'
            'export DEMO_FRONT_PORT="30000"\n'
            'export DEMO_FRONT_URL="http://127.0.0.1:30000"\n'
            'export DEMO_DB_PORT="30001"\n'
        )
        jar = Jar.load(work_path / "jar.json")
        assert jar.ports == {
            f"demo:{work_name}:DEMO_FRONT_PORT": 30000,
            f"demo:{work_name}:DEMO_DB_PORT": 30001,
        }

    def test_rerun_keeps_ports(self, work_path: Path) -> None:
        main()
        first = (work_path / ".envrc.devconfig").read_text()

        main()

        assert (work_path / ".envrc.devconfig").read_text() == first
