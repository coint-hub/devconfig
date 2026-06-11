# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A small CLI that gives local dev projects stable, non-conflicting port assignments and generates env files from them. A target project runs `devconfig.sh`, which reads the project's `devconfig.json`, allocates ports from a global registry, and writes `.envrc.devconfig` (consumed by direnv) into that project.

## Environment & commands

The toolchain comes from `shell.nix` (pinned nixpkgs unstable: Python 3.14, uv, ruff, basedpyright, ty) and is loaded via direnv (`.envrc` → `use nix`). Dependencies are managed by uv as a workspace: root `pyproject.toml` is a non-package workspace whose only member is `devconfig/`.

- Run the CLI: `./devconfig.sh` — must be invoked with the *target project* as cwd (the script `exec`s `direnv exec` + `uv run` against this repo, but `Config.work_path = Path.cwd()`). It sets `DEVCONFIG_JAR` to this repo's `jar.json`.
- Lint: `ruff check`
- Format: `ruff format`
- Type check: `basedpyright` (configured in `pyrightconfig.json` with `typeCheckingMode: "all"`)
- Sync deps: `uv sync`

There are no tests currently.

## Architecture

All logic lives in a single file: `devconfig/src/devconfig/bin/main.py` (Typer CLI, Pydantic models). Data flow:

1. **Jar** (`jar.json` at repo root, gitignored, located via `DEVCONFIG_JAR`) — the persistent global port registry. Ports are assigned sequentially from 30000 and keyed `{config_name}:{work_name}:{KEY}`, so the same project/worktree/service always gets the same port. The jar is saved back after every run.
2. **DevConfig** (`devconfig.json` in the target project's cwd) — declares a config `name` and a list of `services`, each with a `name` and optional `type` (`spring` | `web`) and `path`.
3. **Render** — each service gets a `*_PORT` env var; `spring`/`web` types also get a `*_URL`. `spring` services additionally have `application-default.yml` written into their `path` with `server.port`. Env var names are built by `_key()`: parts joined with `_`, uppercased (e.g. `NAMUHX_BACKEND_ADMIN_API_PORT`).
4. **Output** — all values are written as `export KEY="value"` lines to `.envrc.devconfig` in the target project.

`work_name` is the cwd's directory name, which makes port assignments per-git-worktree (e.g. running from `foo.worktree/main` vs `foo.worktree/feature` yields separate ports).

Note: the code relies on Python 3.14's deferred annotation evaluation (PEP 649) for forward references — no `from __future__ import annotations` needed; don't downgrade the pinned Python version.

`jar.json` is local state and gitignored — never commit it.
