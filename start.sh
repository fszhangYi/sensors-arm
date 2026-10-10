#!/usr/bin/env bash
# Start sensors-arm viz backend.
#
# Usage:
#   ./start.sh
#   ./start.sh configs/default.yaml
#   ./start.sh --log logs/arm.log
#   ./start.sh -c configs/default.yaml --log /tmp/sensors-arm.log
#   SENSORS_ARM_LOG=logs/run.log ./start.sh
#
# --log / SENSORS_ARM_LOG: tee stdout+stderr to the given file (create parent dirs).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

CFG="${SENSORS_ARM_CONFIG:-configs/default.yaml}"
LOG="${SENSORS_ARM_LOG:-}"
EXTRA=()
CFG_FROM_POS=

usage() {
  cat <<'EOF'
Usage: ./start.sh [config.yaml] [options]

Options:
  -c, --config PATH   Config YAML (default: configs/default.yaml)
  -l, --log PATH      Append terminal stdout/stderr to this file (tee)
  --ui                Open system browser
  --no-dry-run        Force dry_run=false
  --port N            Override viz port
  -h, --help          Show this help

Env:
  SENSORS_ARM_CONFIG  Same as --config
  SENSORS_ARM_LOG     Same as --log
  SENSORS_ARM_UI=1    Same as --ui
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    -c|--config)
      [[ $# -ge 2 ]] || { echo "error: $1 needs a path" >&2; exit 1; }
      CFG="$2"
      shift 2
      ;;
    -l|--log)
      [[ $# -ge 2 ]] || { echo "error: $1 needs a path" >&2; exit 1; }
      LOG="$2"
      shift 2
      ;;
    --ui|--no-dry-run)
      EXTRA+=("$1")
      shift
      ;;
    --port)
      [[ $# -ge 2 ]] || { echo "error: --port needs a number" >&2; exit 1; }
      EXTRA+=(--port "$2")
      shift 2
      ;;
    -*)
      echo "error: unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
    *)
      if [[ -z "$CFG_FROM_POS" ]]; then
        CFG="$1"
        CFG_FROM_POS=1
        shift
      else
        echo "error: unexpected argument: $1" >&2
        usage >&2
        exit 1
      fi
      ;;
  esac
done

if [[ -n "${SENSORS_ARM_UI:-}" ]]; then
  EXTRA+=(--ui)
fi

export PYTHONUNBUFFERED=1

if [[ -n "$LOG" ]]; then
  log_dir="$(dirname -- "$LOG")"
  mkdir -p -- "$log_dir"
  # shellcheck disable=SC2094
  echo "[start.sh] logging stdout/stderr → $LOG (also on terminal)" >&2
  # Redirect this shell's stdout/stderr through tee, then replace with python
  # so the child inherits the tee'd FDs.
  exec > >(tee -a -- "$LOG") 2>&1
fi

echo "[start.sh] config=$CFG"
exec python -m sensors_arm.desktop_main -c "$CFG" "${EXTRA[@]+"${EXTRA[@]}"}"
