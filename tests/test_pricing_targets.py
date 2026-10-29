"""Tests for the unified pricing engine: per-service + per-server margins,
single all-inclusive price display, and no panel-cost / profit leaks.

Run from the repository root:

    python3 tests/test_pricing_targets.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "pricing-test")
os.environ.setdefault("BOT_TOKEN", "123:pricing-test")
os.environ.setdefault("ADMIN_ID", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils import markup as mk                     # noqa: E402

PASS = 0


def check(label, cond, detail=""):
    global PASS
    if not cond:
        raise AssertionError(f"FAIL {label} {detail}")
    PASS += 1


def read(*parts):
    return Path(ROOT, *parts).read_text(encoding="utf-8")


def test_targets_registry():
    # services and servers are both priceable
    for svc in mk.SERVICE_ORDER:
        check(f"service {svc} is a target", svc in mk.TARGETS)
    for srv in mk.SERVER_ORDER:
        check(f"server {srv} is a target", srv in mk.TARGETS)
    check("six servers registered", len(mk.SERVER_ORDER) == 6, len(mk.SERVER_ORDER))
    check("label_for server", mk.label_for("srv_bulk") == mk.SERVER_TARGETS["srv_bulk"])
    check("label_for service", mk.label_for("whatsapp") == mk.SERVICES["whatsapp"])


def test_mode_mapping():
    check("bulk -> srv_bulk", mk.server_target_for_mode("bulk") == "srv_bulk")
    check("nonspam -> srv_nonspam", mk.server_target_for_mode("nonspam") == "srv_nonspam")
    check("spam -> srv_spam", mk.server_target_for_mode("spam") == "srv_spam")
    check("numchange -> srv_numchange",
          mk.server_target_for_mode("numchange") == "srv_numchange")
    check("whatsapp -> srv_whatsapp",
          mk.server_target_for_mode("whatsapp") == "srv_whatsapp")
    check("unknown mode -> None", mk.server_target_for_mode("nope") is None)


def test_per_server_override():
    mk.reset_all_markup()
    # No override yet -> server falls back to the global/LZT rule.
    check("server off by default", not mk.is_service_override("srv_spam"))

    mk.set_service_markup("srv_spam", mode="fixed", fixed=70, currency="INR")
    check("server override enabled", mk.is_service_override("srv_spam"))
    check("spam server adds its own margin",
          mk.apply_server_markup(100, "spam") == 170.0,
          mk.apply_server_markup(100, "spam"))
    # A different server is unaffected by the spam override.
    check("bulk server keeps global rule",
          mk.apply_server_markup(100, "bulk") == 125.0,
          mk.apply_server_markup(100, "bulk"))

    # Each server can carry its own numbers.
    mk.set_service_markup("srv_bulk", mode="percent", percent=10)
    check("bulk override is 10%", mk.apply_server_markup(100, "bulk") == 110.0,
          mk.apply_server_markup(100, "bulk"))

    mk.reset_service_markup("srv_spam")
    mk.reset_service_markup("srv_bulk")
    check("spam override cleared", not mk.is_service_override("srv_spam"))
    check("bulk override cleared", not mk.is_service_override("srv_bulk"))


def test_no_cost_or_profit_leak_in_user_screens():
    """User-facing modules must never render the panel cost or profit."""
    for rel in ("plugins/product_panels.py", "plugins/all_apps.py",
                "plugins/buy.py", "plugins/servers.py"):
        src = read(rel)
        # These identifiers only ever belong in admin screens / DB writes.
        for needle in ("bd['real_inr']", 'bd["real_inr"]',
                       "bd['profit_inr']", 'bd["profit_inr"]',
                       "real_inr:", "profit_inr:"):
            check(f"{rel} does not render {needle}", needle not in src)


def test_single_total_price_card():
    """The stock-details card shows ONE price labelled as the total."""
    src = read("utils", "stock_details.py")
    check("card supports a rate label", "rate_label" in src)
    check("card renders the label",
          "rate_label" in src and "html.escape(str(rate_label))" in src)

    pp = read("plugins", "product_panels.py")
    check("product panel labels the price as total",
          'rate_label="Your total price"' in pp)
    check("product panel does not print a duplicate total line",
          "<b>Your total price:</b>" not in pp)
    check("product panel price is service-aware",
          "_price_label(real_price, uid, cfg, service=key)" in pp)

    aa = read("plugins", "all_apps.py")
    check("all_apps labels the price as total",
          'rate_label="Your total price"' in aa)
    check("all_apps does not print a duplicate total line",
          "<b>Your total price:</b>" not in aa)
    check("all_apps no longer multiplies the price by 100",
          "price * 100.0" not in aa)
    check("all_apps uses the allotp service margin",
          'format_service_dual_price(price, "allotp")' in aa)


def test_live_stock_is_real():
    """Stock counts must come from the provider, never a fake number."""
    src = read("utils", "stock_details.py")
    check("stock card shows the exact count", "{count} {unit} available" in src)
    check("stock card never rounds to N+", 'f"{count}+"' not in src)

    pp = read("plugins", "product_panels.py")
    check("product panel fetches live stock", "force=True" in pp)
    check("product panel never claims a fake stock number",
          "40+" not in pp and "50+" not in pp)


def test_database_margin_uses_server_mode():
    import database
    mk.reset_all_markup()
    # Global rule = 25% -> 100 becomes 125.
    check("default margin 25%", database._apply_owner_margin(100) == 125.0,
          database._apply_owner_margin(100))
    # Server-specific override wins when the mode is passed.
    mk.set_service_markup("srv_nonspam", mode="fixed", fixed=40, currency="INR")
    check("nonspam server margin applied",
          database._apply_owner_margin(100, "nonspam") == 140.0,
          database._apply_owner_margin(100, "nonspam"))
    check("other modes keep global",
          database._apply_owner_margin(100, "bulk") == 125.0,
          database._apply_owner_margin(100, "bulk"))
    mk.reset_all_markup()


def main():
    test_targets_registry()
    test_mode_mapping()
    test_per_server_override()
    test_no_cost_or_profit_leak_in_user_screens()
    test_single_total_price_card()
    test_live_stock_is_real()
    test_database_margin_uses_server_mode()
    print(f"OK: {PASS} checks passed")


if __name__ == "__main__":
    main()
