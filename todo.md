# Fix & Upgrade Plan (Numerology bot)

## 1. Fix broken buttons
- [x] Fix reply-keyboard "🛒 ʙᴜʏ ᴀᴄᴄᴏᴜɴᴛ" button (small-caps text not matched)
- [x] Verify all reply-keyboard buttons route correctly

## 2. Country flags everywhere
- [x] Add `utils/flags.py` with full country-name → flag resolver
- [x] Use it in product panels (WhatsApp / Number Change / All Apps)
- [x] Use it in Buy Account country lists + stock pages
- [x] Use it in database.get_flag_by_country_name

## 3. All Apps logos + premium emojis
- [x] Ensure every app button has an icon/logo
- [x] Add premium emojis to panel messages/buttons

## 4. Remove old / stale stock
- [x] Add fresh-stock filter + `/clearoldstock` admin command
- [x] Clear stale price cache on refresh

## 5. Manual "Basic Telegram Account" stock system
- [x] DB table + helpers for manual accounts
- [x] Admin add/list/delete commands
- [x] User-facing panel to browse & buy manual accounts

## 6. Colourful "Get your own Bots" links
- [x] Styled colourful buttons in More Content

## 7. Fix image errors
- [x] "Live price unavailable" error → graceful fallback
- [x] No-stock / price list consistency

## 8. Dual-currency pricing (USDT + INR) with owner margin
- [x] `utils/markup.py`: `price_breakdown`, `format_dual_price`, `format_dual_from_inr`, `format_usdt`, `format_inr`
- [x] Product panels (WhatsApp / Number Change / All Apps): show real cost + margin in INR + USDT
- [x] Buy-account (LZT) buttons, confirm, refund, sold-log: dual currency
- [x] Manual Basic-TG stock: dual currency
- [x] LZT dynamic pricing honours percent OR fixed INR/USD margin
- [x] `/setmargin` alias (25% -> percent, 50 -> fixed INR, 2 USD -> fixed USD) + `/markup` live example
- [x] Verified: no cost leak, no zero price, bad input -> em-dash

## 9. RDX rebrand + premium emojis on every ID
- [x] `QC` -> `RDX` everywhere (config `RDX_ID_PREFIX`, label `RDX ID`, /myid, .env.sample)
- [x] New premium emoji shortcuts: PE_ID, PE_USER, PE_TARGET, PE_TAG, PE_TROPHY, PE_CARD, PE_PHONE, PE_STAR
- [x] Dashboard profile card (NAME / USER ID / USERNAME / RDX ID / BALANCE / VIP) -> premium emojis
- [x] SUPPORT + OWNER lines -> premium emojis (already), staff block Admin/Owner/Super-Admin -> premium
- [x] /profile screen -> premium emojis
- [x] /myid + admin USER INFO + manual Account ID -> premium emojis
- [x] Verified: 8 tg-emoji in dashboard, zero QC left, 18/18 plugins import

## 10. Push to GitHub
- [x] Compile check
- [x] Commit on new branch + push + PR

## 11. Premium sticker pack (country + app aware)
- [x] `utils/stickers.py` engine: parse pack link, load via GetStickerSet, index by emoji + alt text
- [x] Country name -> flag emoji -> sticker; app name -> app emoji -> sticker
- [x] Manual overrides (`/mapsticker` reply-to-sticker) always win
- [x] Send modes: off / country / all; graceful no-op when no pack
- [x] `plugins/stickers.py`: /setpack, /pack, /packsync, /packmode, /packtest, /mapsticker, /unmapsticker, /packmap
- [x] Registered in plugins/__init__.py
- [x] Wired into product_panels (app sticker on All Apps list, country sticker on buy) + all_apps (app + country)
- [x] Help menu entries added
- [x] Verified: compile clean, 19/19 plugins import, handlers register, resolution tested for all countries/apps
- [x] Commit on new branch + push + PR + merge

## 12. Three premium custom-emoji packs + spelling fixes (Request E)
- [x] `utils/stickers.py` rewritten as three-role engine (flags / apps / misc)
- [x] `parse_pack_link` now accepts `t.me/addemoji/...` (custom emoji packs), not just addstickers
- [x] Detect `DocumentAttributeCustomEmoji` and render true premium `<tg-emoji emoji-id=...>`
- [x] Per-role settings keys + caches (sticker_pack_flags/apps/misc)
- [x] `config.py`: STICKER_PACK_FLAGS=FlagsEmoji2024, STICKER_PACK_APPS=ApplicationEmoji, STICKER_PACK_MISC=exppwebs_by_fStikBot
- [x] `plugins/stickers.py`: /setpack <role> <link>, /packsync [role], /packtest [name] [role], 3-role /pack card
- [x] `.env.sample` documents the three env vars
- [x] Purchase/success emoji wired into buy.py, product_panels.py, manual_accounts.py, smm.py, source_codes.py, panels.py
- [x] Fixed help_menu.py help-card spelling (regenerated both cards, verified by decode)
- [x] Fixed start.py button typo (All Apps OPP -> OTP)
- [x] Fixed deposit.py "coonn" -> "coin"
- [x] Help card documents new role syntax
- [x] Verified: compile clean, 19/19 plugins import, 129 handlers register, pack-link parsing + role args tested
- [x] Commit on new branch + push + PR + merge

## 13. Country fetch fix + LZT/TemporaSMS hardening (Request F)
- [x] Root cause: `utils/temporasms.py` used invented REST paths (`/api/countries/...`) that do not exist -> every panel returned 0 countries
- [x] Rewrote `utils/temporasms.py` to the real SMS-Activate-compatible protocol: `stubs/handler_api.php?api_key=&action=`
- [x] Implemented actions: getBalance, getCountries, getServices, getPrices/V2/V3, getNumber/V2, getStatus, setStatus
- [x] Tolerant parsers for mixed plain-text (`ACCESS_BALANCE:`, `ACCESS_NUMBER:`, `STATUS_OK:`) and JSON payloads
- [x] Service alias map (telegram->tg, whatsapp->wa, google->go, ...) so config defaults work
- [x] Country resolution: provider numeric id <-> ISO-2/ISO-3/name/dial code (`_resolve_country_id`)
- [x] `get_countries()` returns priced/in-stock rows, deduped by ISO-2, cheapest first
- [x] `utils/otp_providers.py`: TemporaSMS is now the primary provider for All Apps OTP (was 5SIM-only)
- [x] `plugins/all_apps.py`: `_build_countries()` now keys by ISO-2 instead of slug (buy/stock never matched before)
- [x] `plugins/all_apps.py`: text router matches by ISO-2 first, then label fallback
- [x] `plugins/product_panels.py`: `_countries_for()` wrapped in 20s timeout + graceful fallback
- [x] `utils/lzt.py`: added `LZT_SUPPORTED_ISO3` (155-code enum) and only send `country[]` when supported
- [x] `utils/lzt.py`: removed invalid `parse_sticky_items` params (3 places)
- [x] `utils/lzt.py`: `_throttle()` releases the global lock before sleeping (no more serialised hangs)
- [x] `utils/lzt.py`: `search_items()` has a 30s timeout and tolerant client-side country filter
- [x] `utils/lzt.py`: `get_balance_info()` 10-min cache + timeout + last-known-good (413 shows correctly)
- [x] `plugins/admin_actions.py`: `lzttest` 35s timeout, honest error messaging (no misleading "0 items")
- [x] Text routers cross-clear each other's state so one message can never trigger two replies
- [x] Verified with mocked transport: balance 413.0, countries ru/jp, buy by ISO + by name, OTP, cancel
- [x] Verified OTP provider layer: providers=['temporasms'], stock/price/buy/otp all OK
- [x] `python3 -m compileall` clean; no `parse_sticky_items` / invented REST paths remain
- [ ] Commit on new branch + push + PR
