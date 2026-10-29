# 🚀 Deployment Guide — Environment Variables (Hindi / Hinglish)

Ye file batati hai ki **kaun sa variable kahan paste karna hai**. Sabse important
baat pehle:

> **TemporaSMS key aur Temp Mail key ko env me daalna OPTIONAL hai.**
> Aap dono ko seedha bot ke **Admin Panel** se set kar sakte ho, aur wahan se
> kabhi bhi change kar sakte ho — redeploy ki zarurat nahi.
>
> - OTP / SMS key → **Admin Panel → 🔐 OTP / SMS Key**
> - Temp Mail key / provider → **Admin Panel → 📧 Temp Mail (API)**

Priority order har setting ke liye ye hai:

```
Admin Panel (SQLite settings)  >  Environment Variable  >  Built-in default
```

Matlab: agar aapne panel se key save ki hai, to env variable ko ignore kiya
jayega. Env variable sirf **first boot / fallback** ke liye hai. Panel se
"Reset to ENV" dabane par wapas env value chalu ho jati hai.

---

## 1. Sabse zaruri variables (bot start hone ke liye)

| Variable | Kahan se milega | Example |
|---|---|---|
| `API_ID` | https://my.telegram.org → API development tools | `1234567` |
| `API_HASH` | Same page | `a1b2c3d4e5f6...` |
| `BOT_TOKEN` | [@BotFather](https://t.me/BotFather) → `/newbot` | `123456:ABC-DEF...` |
| `ADMIN_ID` | Aapki Telegram user ID ([@userinfobot](https://t.me/userinfobot)) | `123456789` |

Inke bina bot boot nahi hoga (`validate_runtime_config()` fail karega).

---

## 2. OTP / SMS — TemporaSMS (teeno panels ki ek hi key)

| Variable | Default | Kya karta hai |
|---|---|---|
| `TEMPORASMS_API_KEY` | *(khaali)* | **Main key.** WhatsApp Accounts + TG Number Change + All Apps OTP, teeno isi se chalte hain. |
| `TEMPORASMS_BASE_URL` | `https://api.temporasms.com` | API endpoint. Sirf tab badlo jab provider ka URL alag ho. |
| `TEMPORASMS_SERVICE_WHATSAPP` | `whatsapp` | WhatsApp panel ka service slug. |
| `TEMPORASMS_SERVICE_NUMCHANGE` | `telegram` | Number-change panel ka service slug. |
| `TEMPORASMS_SERVICE_ALLOTP` | `telegram` | All-Apps OTP ka default service slug. |
| `TEMPORASMS_COUNTRY_WHATSAPP` | `any` | Default country (optional). |
| `TEMPORASMS_COUNTRY_NUMCHANGE` | `any` | Default country (optional). |
| `TEMPORASMS_COUNTRY_ALLOTP` | `any` | Default country (optional). |

Key kahan se: **temporasms.com → Dashboard → API Key**.

⚠️ TemporaSMS ka `handler_api.php` `operator` parameter maangta hai. Bot khud
service slug ke hisaab se sahi operator (jaise `telegram → tvm`, operator `13`)
bhej deta hai — aapko manually kuch nahi karna.

**Sabse aasan tareeka (recommended):** env me kuch bhi na daalo, bot start karo,
phir `Admin Panel → 🔐 OTP / SMS Key → Change API Key` me key paste kar do.
Ye SQLite me save hoti hai, restart ke baad bhi rehti hai, aur turant live ho
jati hai — redeploy nahi chahiye.

---

## 3. Temp Mail — Grabmail.io (naya provider)

| Variable | Default | Kya karta hai |
|---|---|---|
| `TEMPMAIL_ENABLED` | `on` | Master switch. `off` karne par users ko Free Temp Mail button nahi dikhega. Panel se bhi toggle ho sakta hai. |
| `GRABMAIL_API_KEY` | *(khaali)* | Grabmail key, `gm_live_...` format. Optional — free domains bina key chalti hain. |
| `GRABMAIL_BASE_URL` | `https://grabmail.io/api/v1` | API base. |
| `GRABMAIL_WEBSITE_URL` | `https://grabmail.io` | Users ko dikhne wala website link. |
| `GRABMAIL_DOMAIN` | `grabmail.io` | Free public domain. Khaali chhodo to `/domains` se auto-pick. |

Key kahan se: **https://grabmail.io → Dashboard → API Keys**.

Grabmail free plan ki limits (bot inhe handle karta hai, 429 par retry):
- 1 request/second, 60/minute, 1000/day
- Free public domains: `grabmail.io`, `mixozia.com`, `linqmail.com`
- Premium `.com` domains ke liye paid plan chahiye
- Messages 5 din baad auto-delete

**Panel se badalna:** `Admin Panel → 📧 Temp Mail (API)` → **Turn ON / Turn OFF**,
API Key, Base URL, Website Link, Domain — sab wahin se editable hai, bina redeploy.
"Test Create Inbox" button se turant verify kar sakte ho.

**ON/OFF kaise kaam karta hai:** panel me **Turn OFF for users** dabao to
user-side "Free Temp Mail" button gayab ho jata hai aur `/tempmail` bhi band ho
jata hai. **Turn ON for users** dabao to turant wapas chalu. Setting database me
save hoti hai, isliye restart/redeploy ke baad bhi bani rehti hai.

---

## 4. Baaki optional variables

| Variable | Kya karta hai |
|---|---|
| `MONGO_URI` | MongoDB mirror (orders/deposits/events history). Khaali = SQLite only. |
| `MONGO_DB` | DB naam, default `numerology_bot`. |
| `LZT_API_KEY` | LZT Market se TG accounts (Good Quality / Cheap stock). |
| `LZT_MARGIN` | LZT items par INR markup, default `25.0`. |
| `TRUST_WALLET_ADDRESS` | USDT (BEP-20) receive address. |
| `SUPPORT_URL`, `OWNER_URL`, `UPDATES_URL`, `MAIN_CHANNEL_URL` | Official links. |
| `CHECK_CHANNELS`, `JOIN_URLS` | Force-join channels. |
| `IMAP_HOST/PORT/USER/PASSWORD` | Telegram login code auto-read karne ke liye. |
| `FIVESIM_API_KEY`, `SMSACTIVATE_API_KEY`, `SMSPVA_API_KEY`, `SMSMAN_API_KEY` | Extra OTP fallbacks (optional). |
| `DEFAULT_MARKUP_*` | Profit engine defaults. |
| `SERVERS_CONFIG` | Server list + mode. |

Poori list `.env.sample` me comment ke saath hai.

---

## 5. Railway par kaise daalein

1. https://railway.app → **New Project → Deploy from GitHub repo**.
2. Repo select karo → service khul jayegi.
3. Service par click → **Variables** tab.
4. **+ New Variable** → `RAW Editor` (sabse fast).
5. Neeche wala block paste karo aur values bhar do:

```
API_ID=1234567
API_HASH=a1b2c3d4e5f6...
BOT_TOKEN=123456:ABC-DEF...
ADMIN_ID=123456789
TEMPORASMS_API_KEY=
GRABMAIL_API_KEY=
```

6. **Deploy** dabao. Logs me `Bot started` dikhna chahiye.
7. Uske baad panel se keys set kar sakte ho — dobara deploy ki zarurat nahi.

> Railway par `PORT` ki zarurat nahi (ye polling bot hai, webhook nahi).
> Agar aapne `DB_PATH` set nahi kiya to `bot.db` container ke andar banega —
> redeploy par ud sakta hai. Permanent chahiye to **Volume** mount karo aur
> `DB_PATH=/data/bot.db` set karo.

---

## 6. Render par kaise daalein

1. https://dashboard.render.com → **New → Web Service** (ya Blueprint, repo me
   `render.yaml` already hai).
2. Repo connect karo.
3. **Environment** tab → **Add Environment Variable** (ek-ek karke) ya
   **Add from .env** (bulk paste).
4. Wahi variables daalo jo upar Railway wale block me hain.
5. **Save Changes** → service auto-redeploy hogi.

> `render.yaml` already `envVars` list rakhta hai; jo variable `sync: false` hai
> use dashboard se manually bharna hota hai.

---

## 7. Heroku par kaise daalein

CLI se (sabse aasan):

```bash
heroku create your-bot-name
heroku config:set API_ID=1234567
heroku config:set API_HASH=a1b2c3d4e5f6...
heroku config:set BOT_TOKEN=123456:ABC-DEF...
heroku config:set ADMIN_ID=123456789
heroku config:set TEMPORASMS_API_KEY=your_key
heroku config:set GRABMAIL_API_KEY=gm_live_xxx
git push heroku main
```

Dashboard se: App → **Settings → Config Vars → Reveal Config Vars** → key/value
add karo. Repo me `app.json` bhi hai, isliye "Deploy to Heroku" button se bhi
ho jayega.

---

## 8. Docker / VPS par kaise daalein

```bash
git clone <repo>
cd <repo>
cp .env.sample .env
nano .env          # values bharo
docker build -t otp-bot .
docker run -d --name otp-bot --env-file .env -v $(pwd)/data:/data otp-bot
```

`docker-compose` use kar rahe ho to `.env` file same folder me rakho — compose
khud utha lega.

Bina Docker ke:

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.sample .env && nano .env
bash start.sh
```

---

## 9. Key rotate karni ho to (leak ho gayi ho)

1. Provider dashboard se **purani key revoke** karo, nayi banao.
2. Bot me: `Admin Panel → 🔐 OTP / SMS Key → Change API Key` (ya
   `📧 Temp Mail (API) → Change API Key`).
3. Nayi key paste karo → done. **Redeploy ki zarurat nahi.**

Env se key hataani ho to panel me **Reset to ENV** dabao — override delete ho
jayega aur env/default wapas lag jayega.

---

## 10. Common problems

| Symptom | Fix |
|---|---|
| `TEMPORASMS_API_KEY is not configured` | Admin → 🔐 OTP / SMS Key se key daalo, ya env set karo. |
| `NO_BALANCE` | TemporaSMS wallet recharge karo. |
| `unauthorized` (Grabmail) | Key galat/expired — panel se nayi daalo. |
| `rate_limited` | Bot khud retry karta hai; limit 1 req/sec hai. |
| `unknown_domain` | `GRABMAIL_DOMAIN` free domain hi rakho (`grabmail.io`). |
| Panel me "older version" error | Fix ho chuka hai; bot restart karke naya panel kholo. |
| Bot start hi nahi ho raha | `API_ID`, `API_HASH`, `BOT_TOKEN`, `ADMIN_ID` check karo. |
