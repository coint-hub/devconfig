import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from devconfig.model import DevConfigModel, DevConfigServiceType


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
