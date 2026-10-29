#!/bin/sh
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "Python 3.9 or later is needed. Download it from https://www.python.org/downloads/ and run ./install.sh again."
  exit 1
fi
echo "Creating a private Python environment in .venv ..."
python3 -m venv .venv || exit 1
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r requirements.txt || exit 1
echo "Downloading the Firefox that Playwright drives (about 90 MB) ..."
.venv/bin/python -m playwright install firefox || exit 1
echo
echo "Installed. Next: ./run.sh login"
