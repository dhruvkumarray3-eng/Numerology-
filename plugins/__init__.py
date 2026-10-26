from plugins.start import register_start
from plugins.profile import register_profile
from plugins.deposit import register_deposit
from plugins.admin import register_admin
from plugins.admin_actions import register_admin_actions
from plugins.callbacks import register_callbacks
from plugins.smm import register_smm
from plugins.source_codes import register_source_codes
from plugins.panels import register_panels
from plugins.settings_menu import register_settings
from plugins.servers import register_servers
from plugins.all_apps import register_all_apps
from plugins.more_content import register_more_content
from plugins.product_panels import register_product_panels
from plugins.admin_extras import register_admin_extras
from plugins.help_menu import register_help
from plugins.manual_accounts import register_manual_accounts

def register_all_handlers(bot):
    # Standard Handler Registrations
    register_start(bot)
    register_profile(bot)
    register_deposit(bot)
    register_admin(bot)
    register_admin_actions(bot)
    register_callbacks(bot)
    register_smm(bot)
    register_source_codes(bot)
    register_panels(bot)
    register_settings(bot)
    register_servers(bot)
    register_all_apps(bot)
    register_more_content(bot)
    register_product_panels(bot)
    register_admin_extras(bot)
    register_help(bot)
    register_manual_accounts(bot)

    # Buy Plugin safely load karne ke liye
    try:
        from plugins.buy import register_buy
        register_buy(bot)
    except ImportError:
        # Agar buy.py me register_buy function nahi hai, toh direct module import ho jayega
        import plugins.buy
        print("✅ Buy Plugin Loaded Successfully (Direct Decorator Mode)")
    except Exception as e:
        print(f"⚠️ Buy Plugin Loading Warning: {e}")
