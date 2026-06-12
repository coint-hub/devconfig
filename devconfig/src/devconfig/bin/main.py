import os
from dataclasses import dataclass
from pathlib import Path
from typing import final

import typer

from devconfig.model import (
    DevConfigModel,
    DevConfigServiceModel,
    DevConfigServiceType,
    Jar,
)


def main() -> None:
    jar = Jar.load(Config.jar_path)

    devconfig = DevConfig(
        DevConfigModel.load(Config.devconfig_path), Config.work_path.name, jar
    )
    values = devconfig.render()
    write_envrc(Config.envrc_path, values)

    jar.save(Config.jar_path)


class Config:
    work_path: Path = Path.cwd()
    envrc_path: Path = work_path / ".envrc.devconfig"
    devconfig_path: Path = work_path / "devconfig.json"

    jar_path: Path = Path(os.environ["DEVCONFIG_JAR"]).resolve()


@dataclass
class Property:
    name: str
    value: str


@final
class DevConfig:
    def __init__(self, model: DevConfigModel, work_name: str, jar: Jar) -> None:
        self.model = model
        self.work_name = work_name
        self.jar = jar
        self.services = [DevConfigService(model=s, parent=self) for s in model.services]

    def render(self) -> dict[str, str]:
        values: dict[str, str] = {}
        values[_key(self.model.name, "work_name")] = self.work_name
        for service in self.services:
            for prop in service.render():
                assert prop.name not in values, (
                    f"Duplicate environment variable: {prop.name=}"
                )
                values[prop.name] = prop.value
        return values


@final
class DevConfigService:
    def __init__(self, *, model: DevConfigServiceModel, parent: DevConfig) -> None:
        self.model = model
        self.parent = parent

    @property
    def port(self) -> Property:
        key = _key(self.parent.model.name, self.model.name, "port")
        port = self.parent.jar.get_or_assign_port(
            config_name=self.parent.model.name,
            work_name=self.parent.work_name,
            key=key,
        )
        return Property(key, str(port))

    @property
    def url(self) -> Property | None:
        match self.model.type:
            case DevConfigServiceType.SPRING | DevConfigServiceType.WEB:
                return Property(
                    _key(self.parent.model.name, self.model.name, "url"),
                    f"http://127.0.0.1:{self.port.value}",
                )
            case None:
                return None

    def render(self) -> list[Property]:
        port = self.port
        values = [port]

        # spring config
        match self.model.type:
            case DevConfigServiceType.SPRING:
                self._write_spring_config(port)
            case DevConfigServiceType.WEB | None:
                pass
        # url
        url = self.url
        if url is not None:
            values.append(url)
            print(f"{self.model.name}: {url.value}")

        return values

    def _write_spring_config(self, port: Property) -> None:
        assert self.model.path is not None, (
            f"Path is required for SPRING service: {self.model.name=}"
        )
        yaml_path = (
            self.model.path / "src" / "main" / "resources" / "application-default.yml"
        )
        with open(yaml_path, "w") as f:
            f.write(f"server.port: {port.value}\n")


def write_envrc(envrc_path: Path, values: dict[str, str]) -> None:
    with open(envrc_path, "w") as f:
        for key, value in values.items():
            f.write(f'export {key}="{value}"\n')


def _key(*names: str) -> str:
    return "_".join(names).upper()


if __name__ == "__main__":
    typer.run(main)
