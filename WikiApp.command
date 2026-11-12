#!/bin/bash
# Starts WikiApp on macOS. Before each start, setup.py checks the app's Python environment
# (App Files/.venv); the first time, it creates it and installs the packages (a minute or two).
# If double-clicking it says it can't be opened, run this once in Terminal:
#   chmod +x WikiApp.command
cd "$(dirname "$0")/App Files" || exit 1

fail() {
  echo
  echo "$1"
  read -r -p "Press Return to close this window. " _
  exit 1
}

if [ -x .venv/bin/python ]; then
  .venv/bin/python setup.py || fail "Setup failed."
else
  # First start: find Python 3.11 or newer (from python.org, Homebrew, or on the PATH).
  PY=""
  for candidate in python3.14 python3.13 python3.12 python3.11 \
      /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
      /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
        "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
      PY="$candidate"
      break
    fi
  done
  [ -n "$PY" ] || fail "WikiApp needs Python 3.11 or newer. Install it from https://www.python.org/downloads/ and start WikiApp again."
  "$PY" setup.py || fail "Setup failed."
fi

nohup .venv/bin/python host/wikiapp.py "$@" >/dev/null 2>&1 &
disown
echo "WikiApp is running. You can close this window."
