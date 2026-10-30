"""Tests for the owner-only GitHub self-update (plugins/self_update.py).

Run with:  PYTHONPATH=. python3 tests/test_self_update.py
"""
import io
import os
import sys
import tarfile
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

PASS = 0
FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  \u2705 {label}")
    else:
        FAIL += 1
        print(f"  \u274C {label} {extra}")


def read(path):
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


print("=" * 70)
print(" SELF-UPDATE TESTS")
print("=" * 70)

from plugins import self_update as su

# ---------------------------------------------------------------- 1. config
print("\n[1] Module configuration")
check("repo points at the real repository",
      su.REPO == "dhruvkumarray3-eng/Numerology-", su.REPO)
check("branch defaults to main", su.BRANCH == "main", su.BRANCH)
check("tarball URL is the codeload endpoint",
      su.TARBALL.startswith("https://codeload.github.com/")
      and "/tar.gz/refs/heads/main" in su.TARBALL, su.TARBALL)
check("plugins dir is refreshable", "plugins" in su.CODE_DIRS)
check("utils dir is refreshable", "utils" in su.CODE_DIRS)
check("main.py is refreshable", "main.py" in su.CODE_ROOT_FILES)

# ------------------------------------------------------- 2. file filtering
print("\n[2] Protected files are never overwritten")
for bad in ("bot.db", "bot_session.session", ".env", "notes.log",
            "Screenshot_20261029_224759.jpg", "main.py.bak"):
    check(f"{bad} rejected", not su._is_code_file(bad))
for good in ("main.py", "plugins/deposit.py", "utils/imap_verifier.py",
             "requirements.txt", "scripts/update_from_github.sh"):
    check(f"{good} accepted", su._is_code_file(good))

# ------------------------------------------------- 3. end-to-end extraction
print("\n[3] End-to-end sync from a fake tarball")


def make_tarball(files):
    """Build an in-memory GitHub-shaped tarball."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            payload = data.encode("utf-8")
            info = tarfile.TarInfo(name=f"Numerology--main/{name}")
            info.size = len(payload)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def run_sync(tarball, target):
    """Call _sync_update with urlopen patched to return `tarball`."""
    import urllib.request
    original = urllib.request.urlopen
    urllib.request.urlopen = lambda *a, **k: _FakeResp(tarball)
    try:
        return su._sync_update(target)
    finally:
        urllib.request.urlopen = original


with tempfile.TemporaryDirectory() as tmp:
    # pre-existing stale file that must be replaced
    os.makedirs(os.path.join(tmp, "plugins"), exist_ok=True)
    with io.open(os.path.join(tmp, "plugins", "deposit.py"), "w",
                 encoding="utf-8") as fh:
        fh.write("# OLD BUILD\n")
    # protected file that must survive
    with io.open(os.path.join(tmp, "bot.db"), "wb") as fh:
        fh.write(b"SQLITE-DATA")

    tar_bytes = make_tarball({
        "plugins/deposit.py": "# NEW BUILD\n",
        "plugins/__init__.py": "x = 1\n",
        "plugins/self_update.py": "y = 2\n",
        "utils/imap_verifier.py": "z = 3\n",
        "main.py": "BUILD_TAG = 'v13'\n",
        "bot.db": "CORRUPTED",
        "bot_session.session": "CORRUPTED",
        ".env": "TOKEN=leak",
        "README.md": "ignore me",
    })

    changed, skipped = run_sync(tar_bytes, tmp)

    check("deposit.py reported changed", "plugins/deposit.py" in changed, changed)
    check("__init__.py reported changed", "plugins/__init__.py" in changed)
    check("main.py reported changed", "main.py" in changed)
    check("bot.db NOT in changed list", "bot.db" not in changed, changed)
    check(".env NOT in changed list", ".env" not in changed, changed)
    check("session NOT in changed list",
          "bot_session.session" not in changed, changed)
    check("README.md skipped", "README.md" not in changed, changed)
    check("skipped counter > 0", skipped > 0, skipped)

    check("deposit.py now has new content",
          read(os.path.join(tmp, "plugins", "deposit.py")) == "# NEW BUILD\n")
    check("backup of old file written",
          os.path.exists(os.path.join(tmp, "plugins", "deposit.py.bak")))
    check("new file created",
          os.path.exists(os.path.join(tmp, "plugins", "self_update.py")))
    check("nested dir created",
          os.path.exists(os.path.join(tmp, "utils", "imap_verifier.py")))
    with io.open(os.path.join(tmp, "bot.db"), "rb") as fh:
        check("database untouched", fh.read() == b"SQLITE-DATA")
    check(".env never written", not os.path.exists(os.path.join(tmp, ".env")))

    # second run must be a no-op (idempotent)
    changed2, _ = run_sync(tar_bytes, tmp)
    check("second run reports no changes", changed2 == [], changed2)

# ------------------------------------------------------- 4. wiring checks
print("\n[4] Handler wiring")
init_src = read("plugins/__init__.py")
check("plugin imported in loader",
      "from plugins.self_update import register_self_update" in init_src)
check("plugin registered in _PLUGIN_REGISTRARS",
      '("self_update", register_self_update)' in init_src)

admin_src = read("plugins/admin.py")
check("admin panel has Update Bot button", "adm_updatebot" in admin_src)

actions_src = read("plugins/admin_actions.py")
check("callback adm_updatebot handled", 'action_data == "adm_updatebot"' in actions_src)
check("update runs off the event loop",
      "asyncio.wait_for(_run_update(" in actions_src)
check("callback guarded by permission",
      'action_data == "adm_updatebot" and has_perm(uid, \'p_settings\')' in actions_src)

su_src = read("plugins/self_update.py")
check("uses asyncio.to_thread", "asyncio.to_thread" in su_src)
check("owner-only guard present", "is_super_admin(uid)" in su_src)
check("never touches .db", '".db"' in su_src)

# ------------------------------------------------------- 5. update script
print("\n[5] Container update script")
sh = read("scripts/update_from_github.sh")
check("uses the full tarball", "codeload.github.com" in sh)
check("no hardcoded FILES list", "FILES=(" not in sh)
check("copies .py files", "*.py" in sh)
check("skips non-code files", "*) continue ;;" in sh)

# ------------------------------------------------------------- 6. build tag
print("\n[6] Build tag")
main_src = read("main.py")
check("BUILD_TAG bumped to v15", "2026-10-30-imap-multiaccount-v15" in main_src)

print("\n" + "=" * 70)
print(f" RESULT: {PASS} passed, {FAIL} failed")
print("=" * 70)
sys.exit(1 if FAIL else 0)
