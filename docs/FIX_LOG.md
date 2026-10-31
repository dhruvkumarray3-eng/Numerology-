# Fix Log — Numbott (Telethon)

Ye file har bade bug ka **root cause + fix + lesson** record karti hai, taaki
koi bhi banda (ya future me main khud) wahi galti dobara na kare.

Har entry me: **Symptom → Root cause → Fix → Lesson (shiksha)**.

---

## 0. "Agree & Continue" terms screen never appeared on product buttons

**Symptom**

Owner recording ke mutabik, **WhatsApp Panel**, **TG Number Change**,
**All Apps OTP**, aur **Good Quality / Cheap TG** buttons dabate hi seedha
country list / app list / account catalogue khul jata tha. Har product ka
apna Terms & Conditions ("Agree & Continue") screen aana chahiye tha, par
woh skip ho raha tha.

**Root cause**

`plugins/product_panels.py` ka `_terms_accepted()` teen layers check karta
tha: in-process memory, per-panel `settings` row, aur **global
`users.terms_accepted`** flag. `/start` par user generic terms accept kar
leta tha → `users.terms_accepted = 1` set ho jata tha → uske baad **har**
panel ka gate `True` return kar deta tha. Isliye per-panel terms screen kabhi
render hi nahi hota tha. `_accept_terms()` bhi `(uid, "*")` wildcard set
karta tha, jo ek panel accept karne par baaki sab ko bhi accepted maan leta
tha.

**Fix**

- `_terms_accepted()` ab **sirf per-panel** check karta hai (memory +
  `pp_tc_<uid>_<key>`). Global `users.terms_accepted` fallback hata diya.
- `_accept_terms()` se `(uid, "*")` wildcard hata diya — har product apna
  acceptance record rakhta hai.
- Naya `PANELS["accounts"]` + `show_accounts_terms()` — Good Quality TG /
  Cheap TG / Buy WP / filters / years ke liye apna terms screen.
- Pending-action dispatcher (`_set_pending` / `_pop_pending` /
  `_run_pending`): user ne jo button dabaya tha, "Agree & Continue" ke baad
  wahi screen khulti hai (country list / filters / years).
- Gates add kiye: `buy.py` (`cb_pg_c`, `cb_pg_filters`, `cb_by_years_menu`)
  aur `servers.py` (`srv_open|bulk|nonspam|spam`).
- Tests: `tests/test_terms_once.py` ko per-panel semantics ke liye update
  kiya, aur naya `tests/test_terms_gate_entrypoints.py` (20 checks) add kiya.

**Lesson (shiksha)**

> Ek "global accepted" flag ko per-product gate ke liye fallback mat banao.
> Global acceptance ka matlab hai "bot use kar sakte ho", per-product
> acceptance ka matlab hai "is service ki shartein maani". Dono alag rakho,
> warna product ka terms screen kabhi nahi dikhega.

**Follow-up (v22) — "abhi bhi nahi aaya"**

Do cheezein add ki gayi taaki update ke baad screen **pakka** dikhe:

1. `TC_VERSION = 2` — `_terms_accepted()` ab sirf wahi acceptance maanta hai
   jiski value current version ke barabar ho. Purani version ki stored value
   (jaise `'1'`) automatically invalid ho jati hai, isliye ek baar terms
   screen dobara aata hai. `_accept_terms()` versioned value (`'2'`) store
   karta hai.
2. `main.py` ka `BUILD_TAG` bump → `2026-10-31-terms-gate-per-product-v22`,
   aur boot par `📜 Terms gate: per-product, TC_VERSION=2` print hota hai.
   Console me ye line na dikhe to container purana code chala raha hai —
   tab `bash scripts/update_from_github.sh` chalao (ya redeploy karo).

> **Note:** Ye repo ka code sahi hai; agar bot phir bhi purana behaviour
> dikhaye to hosting container purane files chala raha hai. Panel shell me
> `bash scripts/update_from_github.sh` chala kar restart karo.

---

## 1. `MediaCaptionTooLongError` — Terms page join ke baad nahi aata tha

**Symptom**

```
telethon.errors.rpcerrorlist.MediaCaptionTooLongError: The caption is too long
(caused by EditMessageRequest)
2026-10-29 13:18:45,232 - telethon.client.updates - ERROR -
Unhandled exception on cb_verify_join
  File "/home/container/plugins/callbacks.py", line 194, in cb_verify_join
    try: await e.edit(terms_message, buttons=get_terms_buttons())
```

User "Verify Joined" dabata tha, kuch nahi hota tha — Terms ke buttons aur main
menu kabhi nahi aate the.

**Root cause**

Channel-join screen **photo** ke saath bhejti hai:

```python
media = types.InputMediaUploadedPhoto(file=f, spoiler=True)
return await bot.send_file(e.chat_id, media, caption=msg, buttons=buttons)
```

Telegram ki limits:

| Message type | Max length |
|---|---|
| Media caption (photo/video) | **1024 chars** |
| Plain text message | **4096 chars** |

`get_terms_message()` = **2529 chars**. Toh photo ko us text ke saath edit karna
impossible hai. Aur code sirf `MessageNotModifiedError` catch karta tha, isliye
exception handler se bahar nikla aur user join screen par atak gaya.

**Fix**

- `utils/helpers.py` → `safe_edit_or_resend(event, text, buttons=None)`:
  1. normal `event.edit()` try;
  2. `MessageNotModifiedError` → success (text already same);
  3. koi bhi dusra error → **photo delete + plain text message resend**
     (4096 budget);
  4. buttons ke saath bhi fail → **bina buttons** retry;
  5. ye function kabhi raise nahi karta.
- `plugins/callbacks.py` → `cb_verify_join` ab isi helper se Terms aur
  "channels remaining" screen bhejta hai.
- `utils/button_safety.py` → `install_edit_safety(bot)`: poore bot ke liye
  global guard jo `CallbackQuery.Event.edit` ko wrap karta hai. Ab kisi bhi
  panel me caption overflow ho toh auto-recover ho jayega.
- `main.py` me handlers register hone se **pehle** install hota hai.

**Lesson (shiksha)**

> Media message ka caption 1024 chars ka hota hai, plain text 4096 ka.
> `e.edit()` ka matlab "us message ko badalna" hai — agar wo message media hai
> toh limit chhoti ho jati hai. Lamba content edit karne ki koshish kabhi na
> karo; delete karke naya text message bhejo.
>
> Aur: `except MessageNotModifiedError` kaafi nahi hai. Telegram RPC errors
> bahut types ke hote hain — handler ke boundary par hamesha broad catch rakho.

---

## 2. `TypeError: 'KeyboardButtonCallback' object is not iterable`

**Symptom**

```
File ".../utils/helpers.py", line 290, in send_preview_on_top
File ".../plugins/start.py", line 162, in send_main_menu
TypeError: 'KeyboardButtonCallback' object is not iterable
```

Terms accept karne ke baad main menu nahi aata tha.

**Root cause**

Telethon `build_reply_markup` ko **list-of-rows** chahiye:

```python
[[btn_a, btn_b], [btn_c]]   # sahi
[btn_a, btn_b]              # GALAT -> TypeError
```

Code me ye pattern tha:

```python
buttons.extend(*([style_btn("📧 ꜰʀᴇᴇ ᴛᴇᴍᴘ ᴍᴀɪʟ", b"tm_home")] if visible else []))
```

`*()` splat ne flat list ko andar daal diya, isliye ek row ki jagah ek button
aa gaya.

**Fix**

1. `plugins/start.py` me `*([[style_btn(...)]] if visible else [])` — ab row
   wrap hoti hai.
2. `utils/helpers.py` → `normalise_buttons()`: None / flat / mixed — sab ko
   list-of-rows me convert karta hai. `send_preview_on_top` ise sabse pehle
   call karta hai.
3. `utils/button_safety.py` → `install_button_safety(bot)`: `build_reply_markup`
   ko wrap karta hai, kharab structure ko repair karke warning log karta hai.
   Markup phir bhi fail ho toh `None` return — message bina keyboard chala
   jayega, handler nahi marega.

**Lesson (shiksha)**

> `list.extend(*x)` almost kabhi sahi nahi hota. Row-based API me hamesha
> "row ki list" banao. Ek jagah fix karne se kaam nahi chalta — **global
> safety net** lagao, kyunki naya panel wahi bug dobara la sakta hai.

---

## 3. `asyncio.CancelledError` se poora process crash

**Symptom**

"The app crashed on an unhandled error" + `asyncio.CancelledError`.

**Root cause**

`asyncio.CancelledError` **`BaseException`** se inherit karta hai, `Exception`
se nahi. `except Exception` use isko pakadta hi nahi — process mar jata hai.

**Fix**

`main.py` me:

```python
except asyncio.CancelledError:
    raise                      # graceful shutdown ke liye re-raise
except BaseException as e:     # baaki sab kuch pakdo
    ...
```

Aur `_supervise()` ne `asyncio.run(main())` ko bhi `except BaseException` me
wrap kiya, plus reconnect loop with 5s/10s/20s/40s backoff.

**Lesson (shiksha)**

> Long-running bot me **do level** ka catch chahiye: handler level aur
> supervisor level. `CancelledError` ko re-raise karo (warna shutdown hang
> hoga), baaki `BaseException` ko log karke chalta raho.

---

## 4. Import-time crashes (`config.py`, `database.py`)

**Symptom**

Missing `API_ID` / `API_HASH` par raw traceback; read-only volume par
`sqlite3.OperationalError`.

**Root cause**

Module import ke waqt `raise RuntimeError(...)` aur DB open — dono fatal.

**Fix**

- `config.py`: inert fallback credentials + `logger.critical` (raise nahi).
- `database.py`: `_open_db()` — WAL fail ho toh DELETE journal, phir temp-dir
  fallback, `busy_timeout=20000`.
- `utils/health.py`: `start_health_server()` kabhi raise nahi karta; ports
  `[PORT, 8080, 8000, 8888, 5000, 3000]` try karta hai, `handle_signals=False`.

**Lesson (shiksha)**

> Import-time side effects (DB open, network, raise) = deploy-time bomb.
> Config missing ho toh **log karo aur chalo**, crash mat karo.

---

## 5. Python 3.14 compatibility

**Symptom**

Live counters chup-chaap band ho gaye; `datetime.utcnow()` deprecation
warnings.

**Root cause**

- `asyncio.get_event_loop()` Python 3.14 par `RuntimeError` deta hai jab koi
  loop running na ho.
- `datetime.utcnow()` deprecated hai.

**Fix**

```python
try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    return          # sync context, kuch karne ki zarurat nahi
```

```python
if exp.tzinfo is None:
    exp = exp.replace(tzinfo=_dt.timezone.utc)
if _dt.datetime.now(_dt.timezone.utc) > exp:
    ...
```

**Lesson (shiksha)**

> `get_event_loop()` bhool jao — `get_running_loop()` use karo. Aur naive
> datetime ko hamesha UTC-aware banao.

---

## 6. Hardcoded script paths

**Symptom**

```
FileNotFoundError: /home/ubuntu/Numbott_Telethon/utils/keyboards.py
```

**Root cause**

`font_updater.py`, `randomize_emojis.py`, `add_blockquotes.py` me absolute
developer path hardcoded tha.

**Fix**

`BASE_DIR = os.path.dirname(os.path.abspath(__file__))` + `os.path.join`,
missing file par `skip`, aur default **dry-run** (`--apply` se hi likhta hai).

**Lesson (shiksha)**

> Kabhi absolute path hardcode na karo. Destructive script ko default dry-run
> rakho.

---

## 7. Temp Mail / TemporaSMS — admin panel se live config

**Symptom**

Admin panel ka Temp Mail button: "Unknown action. This button is designed to
an older version of the panel." Key change karne ke liye redeploy chahiye tha.

**Root cause**

Callback handler register hi nahi tha, aur config sirf env se aata tha.

**Fix**

- `utils/runtime_config.py`: `EDITABLE_KEYS` (tempmail_enabled, api_key,
  base_url, website_url, domain, temporasms_* etc.) SQLite `settings` table me.
- Precedence: **admin panel (DB) → env var → built-in default**.
- `utils/tempmail.py`: sirf **Grabmail.io** (mtempmail hata diya).
- `plugins/admin.py`: ON/OFF toggle + key/base/website/domain edit + test.
- `plugins/tempmail.py`: har entry point par `_tm_on()` gate — OFF ho toh
  "temporarily disabled" notice.
- Bot me "📧 Free Temp Mail" button **rehta hai**, sirf admin toggle se
  hide/show hota hai.

**Lesson (shiksha)**

> "Redeploy ke bina config change" ka matlab hai **DB-backed runtime config**
> with clear precedence. Env var ko default banao, DB ko override.

---

## Golden rules (yaad rakhne wali cheezein)

1. Handler ke andar **kabhi bhi** uncaught RPC error na chhodo — boundary par
   broad catch + log.
2. Media caption = 1024, text = 4096. Lamba text edit na karo, resend karo.
3. Buttons hamesha **list-of-rows**.
4. `CancelledError` re-raise, baaki `BaseException` catch.
5. Import-time par kuch bhi fatal na ho.
6. `get_running_loop()`, UTC-aware datetimes.
7. Paths `__file__` se relative.
8. Global safety nets > individual fixes.
9. Har fix ke saath **regression test**.
10. Deploy ke baad `BUILD_TAG` console me verify karo — warna stale code
    chal raha hota hai aur purane line numbers dikhte hain.

---

## 1. "Panel Reset (All Devices)" — lzt.market terminate session verified

**Symptom**

Buyer ke device list me `Panel Reset (All Devices)` button tha, par owner ko
shak tha ki ye **asli me kaam karta hai ya nahi** — kyunki button render hona
aur callback actually chalna do alag cheezein hain (pehle "Terminate Other
Sessions" button bina handler ke render ho raha tha).

**Root cause / verification**

Kuch toota nahi tha, par koi test **handler** ko end-to-end cover nahi karta
tha — sirf HTTP client (`utils/lzt.py`) ka contract test tha. Handler ke andar
`from utils.lzt import lzt_client` **lazy import** hota hai, isliye
`plugins.buy._lzt` patch karne se test silently asli API hit kar deta tha
(401 aata tha) aur galat cheez "pass" ho sakti thi.

**Fix (verification + hardening)**

- Naya `tests/test_lzt_reset_handler.py` (25 checks): handler registered +
  pattern-bound, button sirf `is_lzt` orders par, 200 → success card +
  cache clear, 403 "Too new authorization" → reason + **live device list**,
  manual order aur stale order par API call **nahi**.
- Test `utils.lzt.lzt_client.telegram_reset_authorizations` ko patch karta hai
  (jahan handler asli me import karta hai), `plugins.buy._lzt` ko nahi.
- Endpoint docs se cross-check: `POST /{item_id}/telegram-reset-authorizations`
  with 200 / 401 / 403 (NoPermission, TelegramFreshAuthorization) / 404 —
  bilkul wahi jo `utils/lzt.py` handle karta hai.

**Lesson**

Jab handler ke andar **lazy import** ho, test me usi module ka object patch
karo jahan se import hota hai. Warna test asli network call kar ke galat
result de sakta hai.
