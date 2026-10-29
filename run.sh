#!/bin/sh
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "Not installed yet. Run ./install.sh first."
  exit 1
fi
exec .venv/bin/python linkedin_scheduler.py "$@"
