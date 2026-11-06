#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

PORT=8042
REPLACE=0
passthrough=()

while [ $# -gt 0 ]; do
  case "$1" in
    --replace) REPLACE=1 ;;
    --port)
      if [ "$#" -lt 2 ]; then echo "--port requires a port number" >&2; exit 2; fi
      PORT="$2"; passthrough+=("$1" "$2"); shift ;;
    --port=*) PORT="${1#*=}"; passthrough+=("$1") ;;
    *) passthrough+=("$1") ;;
  esac
  shift
done

if ! [[ "$PORT" =~ ^[0-9]{1,5}$ ]] || (( 10#$PORT > 65535 )); then
  echo "Port must be an integer between 0 and 65535." >&2
  exit 2
fi

python3 -m pip install --disable-pip-version-check -q -r scripts/requirements.txt

# Return the PID of the first process listening on the configured port, if any.
port_holder() { lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null | head -1 || true; }

holder="$(port_holder)"
if [ -n "$holder" ]; then
  started="$(ps -o lstart= -p "$holder" 2>/dev/null | sed 's/^ *//;s/ *$//' || true)"
  echo "Port ${PORT} is already held by PID ${holder}, started ${started:-unknown}."
  command_line="$(ps -o command= -p "$holder" 2>/dev/null || true)"
  process_dir="$(lsof -a -p "$holder" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' || true)"
  if [[ "$process_dir" != "$(pwd -P)" || ! "$command_line" =~ [[:space:]]explorer/server\.py([[:space:]]|$) ]]; then
    echo "Choose another port. This listener could not be identified as this repository's explorer." >&2
    exit 1
  fi

  replace=$REPLACE
  if [ "$replace" -eq 0 ] && [ -t 0 ]; then
    printf 'Stop it and start a fresh server? [y/N] '
    read -r reply
    case "$reply" in [Yy]*) replace=1 ;; *) replace=0 ;; esac
  fi

  if [ "$replace" -eq 0 ]; then
    echo "Nothing started. To replace it: explorer/run.sh --replace"
    exit 1
  fi

  [ "$(port_holder)" = "$holder" ] || { echo "Port ownership changed." >&2; exit 1; }
  kill "$holder" 2>/dev/null || true
  for _ in $(seq 1 20); do
    [ -z "$(port_holder)" ] && break
    sleep 0.25
  done
  if [ -n "$(port_holder)" ]; then
    echo "Port ${PORT} is still in use." >&2
    exit 1
  fi
  echo "Stopped PID ${holder}."
fi

exec python3 explorer/server.py ${passthrough+"${passthrough[@]}"}
