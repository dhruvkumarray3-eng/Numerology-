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
# This script downloads the WHOLE branch tarball and copies every .py file.
# (The old version used a hand-written FILES list, so any file that was not on
# the list - e.g. plugins/__init__.py - silently stayed stale.  That is gone.)
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
TARBALL="https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH"

cd "$DEST" || { echo "!! cannot cd to $DEST"; exit 1; }

echo "=================================================="
echo " Updating $REPO ($BRANCH) -> $DEST"
echo "=================================================="

if [ -d .git ] && command -v git >/dev/null 2>&1; then
  echo "-> git repository detected, trying a clean pull"
  git fetch --all --prune || true
  git reset --hard "origin/$BRANCH" || git pull --ff-only || true
else
  echo "-> no git repo, downloading the full branch tarball"
  TMP="$(mktemp -d)" || exit 1
  if ! curl -fsSL "$TARBALL" -o "$TMP/repo.tar.gz"; then
    echo "!! download failed - check the container's internet access"
    rm -rf "$TMP"; exit 1
  fi
  tar -xzf "$TMP/repo.tar.gz" -C "$TMP" || { echo "!! extract failed"; rm -rf "$TMP"; exit 1; }
  SRC="$(find "$TMP" -maxdepth 1 -mindepth 1 -type d | head -n1)"
  echo "-> source: $SRC"

  ok=0
  while IFS= read -r -d '' f; do
    rel="${f#"$SRC"/}"
    case "$rel" in
      *.py|*.sh|*.txt|*.json) ;;
      *) continue ;;
    esac
    mkdir -p "$(dirname "$rel")"
    if cp -f "$f" "$rel"; then
      ok=$((ok + 1))
    fi
  done < <(find "$SRC" -type f -print0)

  rm -rf "$TMP"
  echo "-> $ok code files copied (database, session and .env untouched)"
fi

echo
echo "Current build tag:"
grep -m1 'BUILD_TAG =' main.py || true

echo
echo "Done. Now RESTART the server from the panel."
