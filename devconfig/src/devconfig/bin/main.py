import json
import os
from enum import StrEnum, auto, unique
from pathlib import Path

import typer
from pydantic import BaseModel


def main() -> None:
    jar = Jar.load(Config.jar_path)

    devconfig = DevConfig.load(Config.devconfig_path)
    values = devconfig.render(jar, Config.work_path.name)
    write_envrc(Config.envrc_path, values)

    jar.save(Config.jar_path)


class Config:
    work_path: Path = Path.cwd()
    envrc_path: Path = work_path / ".envrc.devconfig"
    devconfig_path: Path = work_path / "devconfig.json"

    jar_path: Path = Path(os.environ["DEVCONFIG_JAR"]).resolve()


class Jar(BaseModel):
    ports: dict[str, int] = {}

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


class DevConfig(BaseModel):
    name: str
    services: list[DevConfigService]

    @staticmethod
    def load(json_path: Path) -> DevConfig:
        with open(json_path, "r") as f:
            return DevConfig.model_validate(json.load(f))

    def render(self, jar: Jar, work_name: str) -> dict[str, str]:
        values: dict[str, str] = {}
        values[_key(self.name, "work_name")] = work_name
        for service in self.services:
            service_values = service.render(
                jar=jar, config_name=self.name, work_name=work_name
            )
            for key, value in service_values:
                assert key not in values, f"Duplicate environment variable: {key=}"
                values[key] = value
        return values


class DevConfigService(BaseModel):
    name: str
    type: DevConfigServiceType | None = None
    path: Path | None = None

    def render(
        self, *, jar: Jar, config_name: str, work_name: str
    ) -> list[tuple[str, str]]:
        values: list[tuple[str, str]] = []

        port_key = _key(config_name, self.name, "port")
        port = jar.get_or_assign_port(
            config_name=config_name, work_name=work_name, key=port_key
        )
        values.append((port_key, str(port)))

        # spring config
        match self.type:
            case DevConfigServiceType.SPRING:
                self._write_spring_config(port)
            case DevConfigServiceType.WEB | None:
                pass
        # url
        match self.type:
            case DevConfigServiceType.SPRING | DevConfigServiceType.WEB:
                url_key = _key(config_name, self.name, "url")
                url = f"http://127.0.0.1:{port}"
                values.append((url_key, url))
                print(f"{self.name}: http://127.0.0.1:{port}")
            case None:
                pass

        return values

    def _write_spring_config(self, port: int) -> None:
        assert self.path is not None, (
            f"Path is required for SPRING service: {self.name=}"
        )
        yaml_path = self.path / "src" / "main" / "resources" / "application-default.yml"
        with open(yaml_path, "w") as f:
            f.write(f"server.port: {port}\n")


@unique
class DevConfigServiceType(StrEnum):
    SPRING = auto()
    WEB = auto()


def write_envrc(envrc_path: Path, values: dict[str, str]) -> None:
    with open(envrc_path, "w") as f:
        for key, value in values.items():
            f.write(f'export {key}="{value}"\n')


def _key(*names: str) -> str:
    return "_".join(names).upper()


if __name__ == "__main__":
    typer.run(main)
