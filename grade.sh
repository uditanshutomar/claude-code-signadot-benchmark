#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")" && pwd)
exec python3 "$root/scripts/setup-only.py" python3 "$root/grader/grade.py" "$@"
