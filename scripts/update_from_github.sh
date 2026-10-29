#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Pull the latest bot code into the hosting container.
#
# WHY THIS EXISTS
# ---------------
# The panel's start command is:
#     cd /home/container && pip install ... && exec python3 -u ${STARTUP_FILE}
# It never runs `git pull`, so the container keeps whatever files were there
# when it was created.  That is why the bot kept booting with an old BUILD tag
# even though main had newer commits.
#
# HOW TO USE
# ----------
# Open the panel's "Console" / "Shell" tab and run:
#
#     bash <(curl -fsSL https://raw.githubusercontent.com/dhruvkumarray3-eng/Numerology-/main/scripts/update_from_github.sh)
#
# ...or copy this file to the container and run `bash scripts/update_from_github.sh`.
# ---------------------------------------------------------------------------
set -uo pipefail

REPO="${REPO:-dhruvkumarray3-eng/Numerology-}"
BRANCH="${BRANCH:-main}"
DEST="${DEST:-/home/container}"

FILES=(
  "main.py"
  "config.py"
  "database.py"
  "requirements.txt"
  "plugins/admin_actions.py"
  "plugins/deposit.py"
  "utils/imap_verifier.py"
  "utils/runtime_config.py"
  "utils/keyboards.py"
  "utils/markup.py"
  "utils/i18n.py"
  "utils/levels.py"
  "utils/smm_client.py"
)

cd "$DEST" || { echo "!! cannot cd to $DEST"; exit 1; }

echo "=================================================="
echo " Updating $REPO ($BRANCH) -> $DEST"
echo "=================================================="

if [ -d .git ] && command -v git >/dev/null 2>&1; then
  echo "-> git repository detected, trying a clean pull"
  git fetch --all --prune || true
  git reset --hard "origin/$BRANCH" || git pull --ff-only || true
else
  echo "-> no git repo, downloading files from raw.githubusercontent.com"
  ok=0
  for f in "${FILES[@]}"; do
    mkdir -p "$(dirname "$f")"
    url="https://raw.githubusercontent.com/$REPO/$BRANCH/$f"
    if curl -fsSL "$url" -o "$f.tmp"; then
      mv "$f.tmp" "$f"
      echo "   ok  $f"
      ok=$((ok + 1))
    else
      rm -f "$f.tmp"
      echo "   !!  $f (download failed)"
    fi
  done
  echo "-> $ok/${#FILES[@]} files updated"
fi

echo
echo "Current build tag:"
grep -m1 'BUILD_TAG =' main.py || true

echo
echo "Done. Now RESTART the server from the panel."
