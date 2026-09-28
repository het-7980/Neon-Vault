#!/bin/sh
cd "$(dirname "$0")" || exit 1
if python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
    exec python3 game.py "$@"
fi
if python -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
    exec python game.py "$@"
fi
printf '%s\n' 'Neon Vault needs Python 3.10 or newer.' 'Install Python, reopen your terminal, and run sh play.sh again.' >&2
exit 1
