#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

PORT=8042
REPLACE=0
passthrough=()

while [ $# -gt 0 ]; do
  case "$1" in
    --replace) REPLACE=1 ;;
    --port) PORT="${2:-$PORT}"; passthrough+=("$1" "${2:-}"); shift ;;
    --port=*) PORT="${1#*=}"; passthrough+=("$1") ;;
    *) passthrough+=("$1") ;;
  esac
  shift
done

python3 -c 'import rdflib' 2>/dev/null ||
  python3 -m pip install -q -r scripts/requirements.txt

# Return the PID of the first process listening on the configured port, if any.
port_holder() { lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null | head -1 || true; }

holder="$(port_holder)"
if [ -n "$holder" ]; then
  started="$(ps -o lstart= -p "$holder" 2>/dev/null | sed 's/^ *//;s/ *$//' || true)"
  echo "Port ${PORT} is already held by PID ${holder}, started ${started:-unknown}."
  echo "That process serves the code it was launched with, not the working tree."

  replace=$REPLACE
  if [ "$replace" -eq 0 ] && [ -t 0 ]; then
    printf 'Stop it and start a fresh server? [Y/n] '
    read -r reply
    case "${reply:-Y}" in [Nn]*) replace=0 ;; *) replace=1 ;; esac
  fi

  if [ "$replace" -eq 0 ]; then
    echo "Nothing started. To replace it: explorer/run.sh --replace"
    exit 1
  fi

  kill "$holder" 2>/dev/null || true
  for _ in $(seq 1 20); do
    [ -z "$(port_holder)" ] && break
    sleep 0.25
  done
  if [ -n "$(port_holder)" ]; then
    echo "PID ${holder} did not stop. Try: kill -9 ${holder}" >&2
    exit 1
  fi
  echo "Stopped PID ${holder}."
fi

exec python3 explorer/server.py ${passthrough+"${passthrough[@]}"}
