import os
import sys
import uuid
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# database imports the Telegram configuration for application startup; the test
# uses harmless placeholders and never connects to Telegram.
os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "catalog-stock-test")
os.environ.setdefault("BOT_TOKEN", "123:catalog-stock-test")
os.environ.setdefault("SUPER_ADMIN_ID", "1")

import database
from plugins.admin_catalogs import _toggle_catalog_visibility


class FakeAdminEvent:
    sender_id = 1

    async def answer(self, *_args, **_kwargs):
        return None

    async def respond(self, text, buttons=None):
        self.last_response = (text, buttons)


def main():
    suffix = uuid.uuid4().hex
    panel_title = f"stock-test-panel-{suffix}"
    source_title = f"stock-test-source-{suffix}"
    try:
        database.cur.execute(
            "INSERT INTO panels (title, description, price, panel_content, available) "
            "VALUES (?, ?, ?, ?, 1)",
            (panel_title, "test", 1.0, "https://example.test",),
        )
        panel_id = database.cur.lastrowid
        database.cur.execute(
            "INSERT INTO source_codes (title, description, price, file_content, available) "
            "VALUES (?, ?, ?, ?, 1)",
            (source_title, "test", 1.0, "zip64:invalid",),
        )
        source_id = database.cur.lastrowid
        database.db.commit()

        panel = next(row for row in database.get_panels() if row[0] == panel_id)
        source = next(row for row in database.get_source_codes() if row[0] == source_id)
        assert len(panel) == 7 and panel[6] == 0
        assert len(source) == 7 and source[6] == 0

        # The actual admin toggle must hide and then re-show the catalog item.
        event = FakeAdminEvent()
        asyncio.run(_toggle_catalog_visibility(event, "panel", panel_id))
        asyncio.run(_toggle_catalog_visibility(event, "source", source_id))
        assert all(row[0] != panel_id for row in database.get_panels())
        assert all(row[0] != source_id for row in database.get_source_codes())
        asyncio.run(_toggle_catalog_visibility(event, "panel", panel_id))
        asyncio.run(_toggle_catalog_visibility(event, "source", source_id))
        assert any(row[0] == panel_id for row in database.get_panels())
        assert any(row[0] == source_id for row in database.get_source_codes())
        print("PASS: catalog stock defaults to zero and hidden listings are excluded")
    finally:
        database.cur.execute("DELETE FROM panels WHERE title=?", (panel_title,))
        database.cur.execute("DELETE FROM source_codes WHERE title=?", (source_title,))
        database.db.commit()


if __name__ == "__main__":
    main()
