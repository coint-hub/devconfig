import json
from enum import StrEnum, auto, unique
from pathlib import Path

# Imported as a bare name because the Jar field below is also called `secrets`;
# `secrets.token_hex()` in a method would read confusingly against `self.secrets`.
from secrets import token_hex

from pydantic import BaseModel, Field


class Jar(BaseModel):
    ports: dict[str, int] = {}
    secrets: dict[str, str] = {}

    @staticmethod
    def load(json_path: Path) -> Jar:
        if not json_path.exists():
            return Jar()

        with open(json_path, "r") as f:
            return Jar.model_validate(json.load(f))

    def save(self, json_path: Path) -> None:
        with open(json_path, "w") as f:
            json.dump(
                self.model_dump(), f, indent=2, sort_keys=True, ensure_ascii=False
            )

    def get_or_assign_port(self, *, config_name: str, work_name: str, key: str) -> int:
        jar_key = f"{config_name}:{work_name}:{key}"
        if jar_key in self.ports:
            return self.ports[jar_key]
        port = 30000 + len(self.ports)
        self.ports[jar_key] = port
        return port

    def get_or_assign_secret(
        self, *, config_name: str, work_name: str, key: str
    ) -> str:
        jar_key = f"{config_name}:{work_name}:{key}"
        if jar_key in self.secrets:
            return self.secrets[jar_key]
        secret = token_hex()
        self.secrets[jar_key] = secret
        return secret


@unique
class DevConfigServiceType(StrEnum):
    SPRING = auto()
    WEB = auto()


class DevConfigServiceModel(BaseModel):
    name: str
    type: DevConfigServiceType | None = None
    path: Path | None = None
    spring_service_references: dict[str, str | list[str]] = Field(
        default={}, alias="springServiceReferences"
    )


class DevConfigModel(BaseModel):
    name: str
    services: list[DevConfigServiceModel]

    @staticmethod
    def load(json_path: Path) -> DevConfigModel:
        with open(json_path, "r") as f:
            return DevConfigModel.model_validate(json.load(f))
