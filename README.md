# devconfig

Stable, non-conflicting port assignments for local dev projects.

Each project declares its services in a `devconfig.json`. Running `devconfig.sh` from the project directory allocates ports from a global registry (`jar.json`, kept in this repo and gitignored) and writes the results as environment variables to `.envrc.devconfig`, ready to be consumed by direnv.

Ports are assigned sequentially from 30000 and keyed by config name, worktree name, and service — so the same project/worktree/service always gets the same port, and parallel git worktrees never collide.

## Usage

From the target project directory:

```sh
/path/to/devconfig.sh
```

Then load the generated file in the project's `.envrc`:

```sh
source_env_if_exists .envrc.devconfig
```

## devconfig.json

```json
{
  "name": "myproject",
  "services": [
    { "name": "postgres" },
    { "name": "backend_api", "type": "spring", "path": "backend/api" },
    { "name": "frontend_web", "type": "web" }
  ]
}
```

Each service gets a `MYPROJECT_<SERVICE>_PORT` variable. Services typed `spring` or `web` also get a `MYPROJECT_<SERVICE>_URL`. For `spring` services, `application-default.yml` containing `server.port` is written into the given `path`.

## Development

The toolchain (Python 3.14, uv, ruff, basedpyright) is provided by `shell.nix` via direnv. See [CLAUDE.md](CLAUDE.md) for details.
