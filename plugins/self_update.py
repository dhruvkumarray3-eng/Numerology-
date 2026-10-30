"""Owner-only self-update command.

Why this exists
---------------
The bot is hosted on a Pterodactyl-style panel whose start command is
``cd /home/container && pip install ... && exec python3 -u ${STARTUP_FILE}``.
There is **no** ``git pull`` in that command, so the container keeps running a
frozen copy of the code no matter how many times a fix is pushed to GitHub.

That is exactly why a fix can be live on GitHub while the running bot still
shows the old behaviour.  ``/updatebot`` closes that gap: it downloads the
latest commit straight from GitHub and drops the ``.py`` files into the running
directory, so the owner only has to press **Restart** in the panel.

Safety rules:
  * only the super admin can run it;
  * only ``.py`` / ``.txt`` / ``.json`` / ``.sh`` files are touched - the
    database (``bot.db``), the Telethon session and ``.env`` are never replaced;
  * the download happens in a worker thread so the event loop never blocks;
  * every replaced file is backed up as ``<name>.bak`` first.
"""
import asyncio
import io
import logging
import os
import shutil
import sys
import tarfile
import urllib.request

from telethon import events

from config import is_super_admin

logger = logging.getLogger(__name__)

# Public repo the bot is deployed from.  Override with GITHUB_REPO=owner/name.
REPO = os.getenv("GITHUB_REPO", "dhruvkumarray3-eng/Numerology-")
BRANCH = os.getenv("GITHUB_BRANCH", "main")
TARBALL = f"https://codeload.github.com/{REPO}/tar.gz/refs/heads/{BRANCH}"

# Directories that hold code we are allowed to refresh.
CODE_DIRS = ("plugins", "utils", "scripts")
CODE_ROOT_FILES = ("main.py", "database.py", "config.py", "requirements.txt")
# Anything matching these is never overwritten.
PROTECTED = (".db", ".session", ".env", ".bak", ".log", ".jpg", ".png")


def _is_code_file(name: str) -> bool:
    low = name.lower()
    if any(low.endswith(bad) for bad in PROTECTED):
        return False
    return low.endswith((".py", ".txt", ".json", ".sh"))


def _sync_update(target_dir: str, timeout: int = 60):
    """Download the branch tarball and copy code files over ``target_dir``."""
    req = urllib.request.Request(
        TARBALL, headers={"User-Agent": "vendor-bot-self-update"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        blob = resp.read()

    changed, skipped = [], 0
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        members = [m for m in tar.getmembers() if m.isfile()]
        for member in members:
            parts = member.name.split("/", 1)
            if len(parts) != 2:
                continue
            rel = parts[1]
            if not _is_code_file(rel):
                skipped += 1
                continue

            top = rel.split("/", 1)[0]
            if "/" in rel:
                if top not in CODE_DIRS:
                    skipped += 1
                    continue
            elif rel not in CODE_ROOT_FILES:
                skipped += 1
                continue

            src = tar.extractfile(member)
            if src is None:
                continue
            data = src.read()

            dest = os.path.join(target_dir, rel)
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)

            old = None
            if os.path.exists(dest):
                try:
                    with open(dest, "rb") as fh:
                        old = fh.read()
                except OSError:
                    old = None
            if old == data:
                continue

            if old is not None:
                try:
                    shutil.copy2(dest, dest + ".bak")
                except OSError:
                    pass
            tmp = dest + ".new"
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, dest)
            changed.append(rel)

    return changed, skipped


async def _run_update(target_dir: str):
    return await asyncio.to_thread(_sync_update, target_dir)


def _restart_process():
    """Replace the running interpreter with a fresh one so new code loads.

    ``os.execv`` keeps the same PID (Pterodactyl's supervisor stays happy) but
    re-reads every module from disk, which is exactly what a stale-bytecode
    process needs after an in-place update.
    """
    argv0 = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else "main.py"
    args = [sys.executable, "-u", argv0]
    logger.warning("Auto-restarting process: %s", " ".join(args))
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    os.execv(sys.executable, args)


def register_self_update(bot_instance):
    @bot_instance.on(events.NewMessage(pattern=r"(?i)^/updatebot(?:@\w+)?$"))
    async def cmd_updatebot(event):
        uid = event.sender_id
        if not is_super_admin(uid):
            return
        target = os.getcwd()
        note = await event.respond(
            "\U0001F504 <b>Checking GitHub for the latest build\u2026</b>\n"
            f"<i>{REPO}@{BRANCH}</i>")
        try:
            changed, skipped = await asyncio.wait_for(
                _run_update(target), timeout=180)
        except asyncio.TimeoutError:
            return await note.edit(
                "\u274C <b>Update timed out.</b>\n"
                "The container could not reach GitHub within 3 minutes.")
        except Exception as exc:
            logger.exception("self-update failed")
            return await note.edit(
                f"\u274C <b>Update failed.</b>\n<code>{type(exc).__name__}: {exc}</code>\n\n"
                "<i>If this is a network error, use the panel's file manager or "
                "the <code>scripts/update_from_github.sh</code> script instead.</i>")

        if not changed:
            return await note.edit(
                "\u2705 <b>Already up to date.</b>\n"
                f"<i>{skipped} non-code files ignored.</i>")

        preview = "\n".join(f"\u2022 <code>{p}</code>" for p in changed[:15])
        if len(changed) > 15:
            preview += f"\n\u2026 and {len(changed) - 15} more"

        auto = os.getenv("AUTO_RESTART_AFTER_UPDATE", "1").strip().lower() not in (
            "0", "false", "no", "off")

        if auto:
            await note.edit(
                f"\u2705 <b>{len(changed)} file(s) updated from GitHub.</b>\n\n"
                f"{preview}\n\n"
                "\U0001F504 <b>Restarting the bot automatically\u2026</b>\n"
                "<i>The new code loads in a few seconds. Your database, session "
                "and settings are untouched.</i>")
            # Give Telegram a moment to deliver the message before exec.
            await asyncio.sleep(3)
            try:
                _restart_process()
            except Exception as exc:  # pragma: no cover - environment specific
                logger.exception("auto-restart failed")
                await note.edit(
                    f"\u2705 <b>{len(changed)} file(s) updated.</b>\n\n"
                    f"{preview}\n\n"
                    f"\u26A0\uFE0F <b>Auto-restart failed:</b> "
                    f"<code>{type(exc).__name__}: {exc}</code>\n"
                    "<i>Please press Restart in the panel.</i>")
            return

        await note.edit(
            f"\u2705 <b>{len(changed)} file(s) updated from GitHub.</b>\n\n"
            f"{preview}\n\n"
            "\u26A0\uFE0F <b>Now press Restart in the panel.</b>\n"
            "<i>The new code only loads after a restart. Your database, session "
            "and settings are untouched.</i>")

    @bot_instance.on(events.NewMessage(pattern=r"(?i)^/(version|build)(?:@\w+)?$"))
    async def cmd_version(event):
        try:
            import main as _main
            tag = getattr(_main, "BUILD_TAG", "unknown")
        except Exception:
            tag = "unknown"
        await event.respond(
            f"\U0001F4E6 <b>Running build:</b>\n<code>{tag}</code>\n\n"
            f"\U0001F310 <b>GitHub:</b> <code>{REPO}@{BRANCH}</code>")
