#!/bin/zsh
cd "${0:A:h}"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Install Python 3 from https://www.python.org/downloads/ and try again.'
  read -r '?Press Return to close.'
  exit 1
fi
python3 app.py
