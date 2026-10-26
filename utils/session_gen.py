"""Utilities to convert Telethon StringSession -> .session file and read sessions."""
import os
import sqlite3
import tempfile
import logging

logger = logging.getLogger(__name__)


def generate_session_from_string(string_session: str):
    """Converts a Telethon StringSession string into a temporary .session file.

    Returns (path, error). On success error is None.
    """
    raw = (string_session or "").strip()
    if not raw:
        return None, "Empty string session."
    if len(raw) < 20:
        return None, "That does not look like a valid StringSession."
    try:
        from telethon.sessions import StringSession
    except Exception as ex:  # pragma: no cover
        return None, f"Telethon not available: {ex}"

    try:
        session = StringSession(raw)
        path = os.path.join(tempfile.gettempdir(), f"generated_{os.getpid()}.session")
        if os.path.exists(path):
            os.remove(path)
        # Build a real SQLiteSession and copy the auth key + DC info.
        from telethon.sessions import SQLiteSession
        sql = SQLiteSession(path)
        sql.set_dc(session.dc_id, session.server_address, session.port)
        sql.auth_key = session.auth_key
        sql.save()
        return path, None
    except Exception as ex:
        logger.error(f"generate_session_from_string error: {ex}")
        return None, str(ex)


def read_session_file(data: bytes) -> str:
    """Reads an uploaded .session (SQLite) file and returns a human summary."""
    if not data:
        return "Empty file."
    tmp = os.path.join(tempfile.gettempdir(), f"read_{os.getpid()}.session")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        conn = sqlite3.connect(tmp)
        try:
            rows = conn.execute("SELECT dc_id, server_address, port FROM sessions").fetchall()
        finally:
            conn.close()
        if not rows:
            return "No sessions table found (file may not be a Telethon session)."
        lines = []
        for dc_id, addr, port in rows:
            lines.append(f"DC {dc_id} → {addr}:{port}")
        return "Valid Telethon session.\n" + "\n".join(lines)
    except Exception as ex:
        return f"Could not parse session file: {ex}"
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
