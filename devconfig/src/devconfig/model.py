import json
from enum import StrEnum, auto, unique
from pathlib import Path

from pydantic import BaseModel


@unique
class DevConfigServiceType(StrEnum):
    SPRING = auto()
    WEB = auto()


class DevConfigServiceModel(BaseModel):
    name: str
    type: DevConfigServiceType | None = None
    path: Path | None = None


class DevConfigModel(BaseModel):
    name: str
    services: list[DevConfigServiceModel]

    @staticmethod
    def load(json_path: Path) -> DevConfigModel:
        with open(json_path, "r") as f:
            return DevConfigModel.model_validate(json.load(f))
