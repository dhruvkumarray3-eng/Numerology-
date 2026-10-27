# Numbott — Telegram Account & Digital Goods Store Bot

Numbott is a modular **Telegram shop bot** built with [Telethon](https://docs.telethon.dev/) (MTProto). It sells Telegram accounts and other digital products, handles a user wallet with USDT (BEP-20) deposits, delivers live account sessions, and gives the owner a full admin panel.

> **This is not a music bot.** Earlier versions of this README described a "Vibe Music Bot" with `/play`, `/pause`, `/skip` and PyTgCalls. That was never part of this repository. There is no audio streaming, no yt-dlp, no FFmpeg and no voice-chat code here. The real project is an account marketplace, and this document describes it accurately.

---

## What the bot actually does

The shop has two sources of Telegram account stock:

1. **Live LZT Market stock** — accounts are searched and purchased in real time through the [LZT Market API](https://api.lzt.market) (`lolz.guru` / `lzt.market`). This is the primary source and powers the **Buy Account → Good Quality** and **Cheap** panels.
2. **Local stock** — accounts uploaded by the owner (session files + phone + 2FA) in the admin panel. Local stock is always checked first; if nothing matches, the bot falls back to a live LZT purchase.

When a purchase succeeds, the bot builds a Telethon `StringSession` from the LZT auth key, verifies that the session is authorised, and shows the buyer a live order card with the phone number, 2FA password, OTP retrieval and session export (Telethon / tdata / Pyrogram / JSON).

### Core features

- **Telegram account marketplace** with country, account-year, price and quality filters. All **249 ISO-3166 countries** resolve to an ISO-2 code and are searchable.
- **Quality modes**: Good Quality (non-spam), Cheap (spam-blocked), No 2FA, With 2FA, Premium, With/Without email, DC-5, Stars, Aged — all configurable by the admin.
- **Live LZT purchase flow** with `retry_request` handling (up to 100 retries), numeric price payload, integer `balance_id`, and human-readable failure reasons.
- **Automatic OTP retrieval** for purchased accounts (`telegram-login-code`), plus an IMAP fallback mailbox.
- **USDT (BEP-20 / BNB Smart Chain) deposits** with an auto-generated QR code and admin approval.
- **Product panels**: WhatsApp OTP accounts, Telegram number change, All-Apps OTP accounts (51 apps), SMM services, panel resale, source codes.
- **Wallet, discounts, referrals, gift codes, VIP tiers, order history.**
- **Admin panel**: stock upload, pricing/markup engine, LZT margin, search settings, user management (ban/balance/broadcast), cleanup/delete centre, premium-emoji packs, live LZT diagnostics.
- **MongoDB is optional** — full history is mirrored to Mongo when `MONGO_URI` is set; SQLite remains the source of truth.
- **Railway/Render/Heroku ready** with a health server on `$PORT`.

---

## Project structure

```
.
├── main.py                  # entrypoint: health server, handler registration, reconnect loop
├── config.py                # env loading, Telegram client, links, API keys
├── database.py              # SQLite schema, users/stock/orders/settings, pricing engine
├── plugins/                 # feature modules (start, buy, deposit, admin, panels, smm, ...)
│   ├── buy.py               # account marketplace + live LZT purchase flow
│   ├── admin*.py            # admin panel, actions, cleanup, extras
│   ├── product_panels.py    # WhatsApp / number change / All-Apps OTP panels
│   └── ...
├── utils/
│   ├── lzt.py               # LZT Market API client (search, fast-buy, OTP, balance)
│   ├── flags.py             # 249-country flag/ISO helpers
│   ├── search_settings.py   # admin-tunable search filters
│   ├── health.py            # aiohttp health server for PaaS probes
│   └── ...
├── tests/                   # standalone regression scripts (no pytest required)
├── Dockerfile
├── railway.json             # Railway start command
├── Procfile                 # web/worker process definitions
├── render.yaml
├── heroku.yml
├── app.json
└── start.sh                 # local venv bootstrap
```

---

## Requirements

- Python **3.11+**
- A Telegram **API ID / API HASH** from <https://my.telegram.org>
- A **bot token** from [@BotFather](https://t.me/BotFather)
- An **LZT Market API token** with the `market` scope (for live account stock)
- Optional: a **TemporaSMS** key (All-Apps OTP, number change, WhatsApp panels)
- Optional: **MongoDB** URI for mirrored history

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

---

## Quick start (local)

1. Copy the sample environment file and fill in the required values:

   ```bash
   cp .env.sample .env
   ```

2. Set at minimum:

   ```env
   API_ID=123456
   API_HASH=your_api_hash
   BOT_TOKEN=123456:your_bot_token
   ADMIN_ID=your_telegram_user_id
   ```

3. Run the bot:

   ```bash
   python3 main.py
   ```

   Or use the bootstrap script (creates a venv, installs requirements, checks `.env`):

   ```bash
   chmod +x start.sh
   ./start.sh
   ```

The bot prints `🚀 NUMBOTT MODULAR (TELETHON) STARTED SUCCESSFULLY!` and then performs a non-fatal LZT self-check. If the market token is missing or invalid, the reason is written to the log at boot.

---

## Environment variables

### Required

| Variable | Description |
| --- | --- |
| `API_ID` | Telegram API ID (integer) |
| `API_HASH` | Telegram API hash |
| `BOT_TOKEN` | Bot token from BotFather |
| `ADMIN_ID` | Owner/admin Telegram user ID |

### Telegram & links (optional, sensible defaults)

| Variable | Description |
| --- | --- |
| `SUPER_ADMIN_ID` | Second owner ID with full privileges |
| `LOG_CHANNEL_ID` | Channel where bot events are logged |
| `LOG_CHANNEL_ID_2` | Secondary log channel |
| `CHECK_CHANNELS` | Force-join channel(s), comma/space separated |
| `JOIN_URLS` | Force-join URLs matching `CHECK_CHANNELS` |
| `SUPPORT_URL` | Support group link |
| `OWNER_URL` | Owner contact link |
| `UPDATES_URL` | Updates channel link |
| `MAIN_CHANNEL_URL` | Main network channel |
| `TERMS_URL` | Terms & conditions link |

### Payments

| Variable | Description |
| --- | --- |
| `TRUST_WALLET_ADDRESS` | USDT BEP-20 receiving address |
| `TRUST_WALLET_QR` | Optional custom QR image URL/file_id (auto-generated if blank) |
| `USDT_TO_INR` | USDT→INR rate used for display (default `88.0`) |
| `ADMIN_PROFIT_INR` | Default flat profit added to panel prices |

### LZT Market

| Variable | Description |
| --- | --- |
| `LZT_API_KEY` | LZT Market token with `market` scope. Can also be set in Admin → LZT Panel Settings |
| `LZT_MARGIN` | Fixed INR markup applied to automatically priced LZT items |

> LZT requires **200 sympathies** or a paid subscription to use the market API. A token without access returns `401/403`; the bot logs this at startup and shows it in the admin diagnostics.

### OTP / SMS providers

| Variable | Description |
| --- | --- |
| `TEMPORASMS_API_KEY` | Main key for All-Apps OTP, number change and WhatsApp panels |
| `TEMPORASMS_BASE_URL` | Default `https://api.temporasms.com` |
| `FIVESIM_API_KEY`, `SMSACTIVATE_API_KEY`, `SMSPVA_API_KEY`, `SMSMAN_API_KEY`, `TEMPMAIL_API_KEY` | Optional fallbacks |
| `IMAP_HOST`, `IMAP_PORT`, `IMAP_USER`, `IMAP_PASSWORD` | Mailbox used to auto-read Telegram codes |

### Other

| Variable | Description |
| --- | --- |
| `MONGO_URI` | Optional MongoDB URI for mirrored history |
| `PORT` | Health-server port (Railway/Render set this automatically) |
| `BOT_HEALTH_PORT` | Override the health-server port |
| `ALL_APPS_CATALOG_JSON` | JSON override for the All-Apps catalog |
| `SERVERS_CONFIG` | `name|status|mode` list shown in the Servers screen |
| `DEFAULT_CURRENCY` | Display currency (default `INR`) |

---

## How the LZT purchase flow works

1. The buyer picks a country, account year and quality mode.
2. `LZTClient.search_items()` calls `GET /telegram` with `country[]`, `spam`, `allow_geo_spamblock`, `password`, `premium`, `email`, `dc_id[]`, `min_stars`, `session_age` and price bounds. Pages are followed via `nextCursor`/`after`.
3. Each item is normalised by `_parse_item()`: price, phone, year, 2FA, email, premium, stars, DC and the spam flag (`-3` real spam, `>0` spam days, `0` clean, `-1/-4/None` unknown/geo).
4. On confirm, `process_purchase()` debits the wallet and calls `LZTClient.fast_buy(item_id, price, balance_id)`.
5. `fast_buy()` sends `POST /{item_id}/fast-buy` with a **numeric** `price`. `balance_id` is **optional** and is only sent when the caller explicitly supplies a funded wallet; otherwise LZT charges the main market balance. If the price is unknown the field is omitted so LZT charges the current listing price. `retry_request` is retried up to 100 times with backoff, and an "insufficient funds" reply on a pinned wallet is retried once without `balance_id`.
6. On success, the bot takes the phone from `item.telegram_phone` (never from `item.login`, which holds the 512-character auth-key hex for Telegram items), the 2FA password from `item.loginData.password`, builds a `StringSession` from `loginData.raw` / `loginData.login` + `telegram_dc_id`, verifies `is_user_authorized()`, and shows the order card.
7. OTP retrieval (`GET /{item_id}/telegram-login-code`) parses the `codes` **array**, picks the newest entry and ignores codes received before the order started, so a buyer never sees an expired code.
8. Any failure (market error, dead session, mismatch) refunds the buyer's wallet and reports a clear reason.

### Verified against the live market

The flow above was exercised end to end against `api.lzt.market` with a real token and real purchases:

| Check | Result |
| --- | --- |
| `GET /me` | 200, account resolved, main wallet read in RUB + USD |
| `GET /telegram?country[]=IN` | 200, 76k+ listings (ISO-2 **uppercase** required; lowercase or full names return 0) |
| `POST /{id}/fast-buy` without `balance_id` | 200, `item_state: paid` |
| `POST /{id}/fast-buy` with an empty sub-wallet id | 403 "not enough money" -> automatic retry without the id -> 200 |
| `StringSession` from the purchase payload | parses, correct DC and 256-byte auth key |
| `GET /{id}/telegram-login-code` | 200, `codes` array parsed, stale codes filtered |
| `check_connection()` | 200, shows `387.00 RUB (~4.81 USD)` |

`tests/live_lzt_check.py` repeats the read-only part of that sweep (it never spends money).

### Purchase troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| "The shop's LZT balance is too low" | LZT wallet empty | Top up the LZT market balance |
| "The LZT API key is invalid or expired" | Token missing `market` scope / expired | Regenerate the token and update Admin → LZT Panel Settings or `LZT_API_KEY` |
| "The seller has blacklisted this shop" | Seller blocked the buyer account | Try another listing/country |
| "The daily purchase/check limit ... reached" | LZT rate limit | Wait and retry |
| "This account was just sold" | Listing disappeared between search and buy | The bot automatically tries the next item |
| "Out of stock (no local stock and no LZT market key)" | No local stock and live search disabled/unconfigured | Set `LZT_API_KEY` and enable live search |
| "No live accounts found" | Token invalid, filters too strict, or country has no stock | Check Admin → LZT diagnostics; relax filters |
| Search returns 0 for every country | `country[]` must be ISO-2 **uppercase** (`IN`, not `in` or `India`) | Handled by `get_lzt_code2()`; do not send raw country names |
| "The shop's LZT balance is too low" although the account is funded | An empty sub-wallet id was pinned | `fast_buy()` now omits `balance_id` and retries automatically |

A regression test (`tests/test_buy_fixes.py`) covers the clean-account (`telegram_spam_block == 0`) case that previously caused every non-spam purchase to be discarded with a refund.

---

## Deploying to Railway

The repository is ready for Railway:

1. Create a new Railway project and connect this GitHub repository.
2. Add the required variables under **Variables** (`API_ID`, `API_HASH`, `BOT_TOKEN`, `ADMIN_ID`, `LZT_API_KEY`, and any optional keys).
3. Railway uses `railway.json` → `python main.py`. No build command is required beyond installing `requirements.txt`.
4. The health server listens on `$PORT`; Railway's health check can target `/health` or `/ping`.
5. Watch the deploy logs for `STARTED SUCCESSFULLY` and the LZT self-check line.

`Procfile`, `render.yaml`, `heroku.yml`, `app.json`, `Dockerfile` and `start.sh` are included for other platforms. On platforms that provide `$PORT`, the health server binds to it automatically; otherwise it defaults to `8080`.

---

## Commands

### User commands

| Command | Description |
| --- | --- |
| `/start` | Main menu / dashboard |
| `/menu` | Reopen the persistent keyboard |
| `/hide`, `/close` | Close the keyboard |
| `/rates` | Show panel rates |
| `/redeem <code>` | Redeem a gift code |
| `/myhistory` | Own order and payment history |
| `/myid`, `/id` | Own Telegram ID and chat ID |
| `/support` | Contact support |
| `/help` | Help card |

### Product shortcuts

| Command | Description |
| --- | --- |
| `/whatsapp`, `/wa` | WhatsApp OTP panel |
| `/numchange`, `/numberchange` | Telegram number-change panel |
| `/allotp`, `/otp`, `/apps` | All-Apps OTP panel |
| `/panels`, `/products` | Product hub |
| `/smm` | SMM services |

### Admin commands

| Command | Description |
| --- | --- |
| `/admin` | Full admin panel (stock, ban, balance, broadcast, cleanup, LZT settings) |
| `/setmarkup <percent>` | Set percentage profit |
| `/setprofit <amount> <INR\|USD>` | Set flat profit |
| `/markup` | Show current profit configuration |
| `/resetmarkup` | Reset to default profit |
| `/lztmargin <n>`, `/setlztmargin <n>` | Set per-item LZT markup |
| `/history <user_id>` | Full user history (SQLite + Mongo) |
| `/grant <user_id> <amount>` | Credit a user's balance |
| `/addcode <code> <amount> [uses]` | Create a gift code |
| `/codes` | List gift codes |
| `/panelstats` | Orders, revenue, real cost and profit |
| `/panelsales [n]` | Last *n* panel orders |
| `/panelbalance` | TemporaSMS wallet balance |
| `/mongostatus` | MongoDB connection and counts |
| `/setchangefee <n>` | Number-change fee |
| `/setsticker`, `/setpack`, `/packsync`, `/pack`, `/packtest`, `/packmode`, `/mapsticker` | Premium-emoji pack management |
| `/premiumcheck` | Diagnose premium-emoji rendering |

---

## Tests

The tests are standalone scripts (no `pytest` needed) and stub out Telegram/network calls:

```bash
API_ID=1 API_HASH=x BOT_TOKEN=x python3 tests/test_lzt_spec.py
API_ID=1 API_HASH=x BOT_TOKEN=x python3 tests/test_lzt_errors.py
API_ID=1 API_HASH=x BOT_TOKEN=x python3 tests/test_search_settings.py
API_ID=1 API_HASH=x BOT_TOKEN=x python3 tests/test_buy_fixes.py
```

They cover the LZT spec compliance, error handling, country resolution (all 249 ISO codes), search settings/fallbacks, and the purchase-flow regressions.

You can also sanity-check the whole tree:

```bash
python3 -m compileall -q .
```

---

## Data & security notes

- `otp_bot_final.db` (SQLite) stores users, stock, orders and settings. Back it up before upgrades.
- `bot_session.session` is the bot's own Telethon session — keep it private.
- Never commit `.env`, API tokens, wallet keys or purchased account sessions.
- Purchased account sessions are sensitive credentials; deliver them only to the buyer's private chat and log deliveries to your private log channel.
- The bot only talks to Telegram, the LZT Market API and the configured OTP providers.

---

## License

See [LICENSE](LICENSE).
