#!/usr/bin/env bash
#
# Numbott startup wrapper.
#
# Why this exists
# ---------------
# The default Pterodactyl startup line is:
#
#     if [ -f requirements.txt ]; then pip install -U --prefix .local -r requirements.txt; fi && exec python3 -u main.py
#
# Two problems with that:
#
#   1. ``-U`` forces pip to contact PyPI for *every* package on *every* boot,
#      even though requirements.txt pins exact versions.  That takes 20-60s and
#      is the window in which a panel restart interrupts pip, producing the
#      scary ``KeyboardInterrupt`` traceback in the console.
#   2. The ``&&`` chain means an interrupted/failed pip aborts the whole start,
#      so the bot stays down until the next manual restart.
#
# This script fixes both: it only touches pip when a dependency is genuinely
# missing, never upgrades pinned packages, never lets pip failure block the
# bot, and makes sure ``--prefix .local`` installs are importable.
#
# Usage: set the panel Startup Command to
#
#     bash scripts/start.sh
#
set -u

cd "$(dirname "$0")/.." || exit 1

PY="${PYTHON_BIN:-python3}"

# ``pip install --prefix .local`` writes here; Python does not add it to
# sys.path on its own, so export it explicitly (harmless if already set).
add_local_site() {
    for site in .local/lib/python*/site-packages; do
        [ -d "$site" ] || continue
        case ":${PYTHONPATH:-}:" in
            *":$PWD/$site:"*) ;;
            *) PYTHONPATH="$PWD/$site${PYTHONPATH:+:$PYTHONPATH}" ;;
        esac
    done
    export PYTHONPATH
}
add_local_site

# Every runtime dependency, imported in one go.  If this succeeds we skip pip
# entirely, which is the normal case after the first boot.
deps_ok() {
    "$PY" - <<'PYCHECK' >/dev/null 2>&1
import aiohttp, aiohappyeyeballs, aiosignal, attrs, dotenv, frozenlist
import idna, multidict, pyaes, pyasn1, pymongo, qrcode, requests, rsa
import telethon, typing_extensions, yarl
from PIL import Image
PYCHECK
}

if deps_ok; then
    echo "[start] dependencies OK -> skipping pip"
else
    echo "[start] dependencies missing -> installing (no -U, pinned versions)"
    if [ -f requirements.txt ]; then
        # No -U: requirements.txt pins exact versions, so upgrading is pointless
        # and only adds network round-trips.  ``|| true`` so a flaky mirror can
        # never stop the bot from booting.
        "$PY" -m pip install --disable-pip-version-check --prefix .local \
            -r requirements.txt || true
    fi
    add_local_site
fi

exec "$PY" -u "${STARTUP_FILE:-main.py}"
