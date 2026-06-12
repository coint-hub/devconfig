import json
from pathlib import Path

import pytest

from devconfig.bin.main import (
    Config,
    DevConfig,
    Property,
    _key,  # pyright: ignore[reportPrivateUsage]
    main,
    write_envrc,
)
from devconfig.model import DevConfigModel, Jar


def test_key_joins_and_uppercases() -> None:
    assert _key("demo", "api", "port") == "DEMO_API_PORT"
    assert _key("demo") == "DEMO"


def _devconfig(services: list[dict[str, str]], work_name: str = "main") -> DevConfig:
    model = DevConfigModel.model_validate({"name": "demo", "services": services})
    return DevConfig(model, work_name, Jar())


class TestDevConfigServiceProperties:
    def test_port_assigns_from_jar(self) -> None:
        devconfig = _devconfig([{"name": "db"}])

        assert devconfig.services[0].port == Property("DEMO_DB_PORT", "30000")

    def test_url_is_none_for_untyped_service(self) -> None:
        devconfig = _devconfig([{"name": "db"}])

        assert devconfig.services[0].url is None

    def test_url_uses_assigned_port(self) -> None:
        devconfig = _devconfig([{"name": "front", "type": "web"}])

        assert devconfig.services[0].url == Property(
            "DEMO_FRONT_URL", "http://127.0.0.1:30000"
        )


class TestDevConfigServiceRender:
    def test_untyped_service_renders_port_only(self) -> None:
        devconfig = _devconfig([{"name": "db"}])

        values = devconfig.services[0].render()

        assert values == [Property("DEMO_DB_PORT", "30000")]

    def test_web_service_renders_port_and_url(self) -> None:
        devconfig = _devconfig([{"name": "front", "type": "web"}])

        values = devconfig.services[0].render()

        assert values == [
            Property("DEMO_FRONT_PORT", "30000"),
            Property("DEMO_FRONT_URL", "http://127.0.0.1:30000"),
        ]

    def test_spring_service_writes_yaml_and_renders_url(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "main" / "resources").mkdir(parents=True)
        devconfig = _devconfig(
            [{"name": "api", "type": "spring", "path": str(tmp_path)}]
        )

        values = devconfig.services[0].render()

        assert values == [
            Property("DEMO_API_PORT", "30000"),
            Property("DEMO_API_URL", "http://127.0.0.1:30000"),
        ]
        yaml_path = tmp_path / "src" / "main" / "resources" / "application-default.yml"
        assert yaml_path.read_text() == "server.port: 30000\n"

    def test_spring_service_without_path_raises(self) -> None:
        devconfig = _devconfig([{"name": "api", "type": "spring"}])

        with pytest.raises(AssertionError):
            devconfig.services[0].render()


class TestDevConfigRender:
    def test_renders_work_name_and_all_services(self) -> None:
        devconfig = _devconfig(
            [{"name": "front", "type": "web"}, {"name": "db"}], work_name="feature"
        )

        values = devconfig.render()

        assert values == {
            "DEMO_WORK_NAME": "feature",
            "DEMO_FRONT_PORT": "30000",
            "DEMO_FRONT_URL": "http://127.0.0.1:30000",
            "DEMO_DB_PORT": "30001",
        }

    def test_duplicate_service_name_raises(self) -> None:
        devconfig = _devconfig([{"name": "db"}, {"name": "db"}])

        with pytest.raises(AssertionError):
            devconfig.render()

    def test_rerender_with_same_jar_keeps_ports(self) -> None:
        devconfig = _devconfig([{"name": "front", "type": "web"}, {"name": "db"}])

        first = devconfig.render()
        second = devconfig.render()

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
