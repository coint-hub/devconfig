import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from devconfig.model import DevConfigModel, DevConfigServiceType, Jar


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


def test_load_parses_valid_devconfig(tmp_path: Path) -> None:
    json_path = tmp_path / "devconfig.json"
    json_path.write_text(
        json.dumps(
            {
                "name": "demo",
                "services": [
                    {"name": "api", "type": "spring", "path": "backend/api"},
                    {"name": "front", "type": "web"},
                ],
            }
        )
    )

    model = DevConfigModel.load(json_path)

    assert model.name == "demo"
    assert len(model.services) == 2
    assert model.services[0].type == DevConfigServiceType.SPRING
    assert model.services[0].path == Path("backend/api")
    assert model.services[1].type == DevConfigServiceType.WEB
    assert model.services[1].path is None


def test_service_optional_fields_default_to_none() -> None:
    model = DevConfigModel.model_validate(
        {"name": "demo", "services": [{"name": "db"}]}
    )

    service = model.services[0]
    assert service.type is None
    assert service.path is None


def test_invalid_service_type_raises() -> None:
    with pytest.raises(ValidationError):
        DevConfigModel.model_validate(
            {"name": "demo", "services": [{"name": "api", "type": "rails"}]}
        )
