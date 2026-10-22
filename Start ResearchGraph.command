#!/bin/zsh
cd -- "${0:A:h}"
if [[ ! -x .venv/bin/python ]]; then
  print 'Set up the Python environment using README.md, then run this launcher again.'
  read '?Press Enter to close.'
  exit 1
fi
.venv/bin/python scripts/serve.py
if [[ $? -ne 0 ]]; then
  read '?Startup failed. Read the error above. Press Enter to close.'
  exit 1
fi
