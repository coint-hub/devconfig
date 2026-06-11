#!/usr/bin/env bash
set -euo pipefail

DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
export DEVCONFIG_JAR="${DIR}/jar.json"
exec direnv exec "${DIR}" uv run --project "${DIR}/devconfig" "${DIR}/devconfig/src/devconfig/bin/main.py" "$@"
