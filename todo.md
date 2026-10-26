# LZT Live Search — ISO-2 Country Fix (Round 6)

## Diagnosis (live-verified against api.lzt.market)
- [x] Token `sub:10623075` is a valid LZT Access Token (3 parts, `eyJ`, `market` scope, exp 2031)
- [x] `GET /me` -> HTTP 200, balance 413.00 usd (auth + market access OK)
- [x] `GET /telegram?country[]=USA` -> totalItems 0, but `country[]=US` -> 20,599
- [x] Root cause #1: LZT `country[]` expects ISO-2 UPPERCASE; bot was sending ISO-3
- [x] Root cause #2: `telegram_spam_block == -4` (geo spam block) was treated as spam and dropped

## Fixes
- [x] Add `get_lzt_code2()` + `LZT_SUPPORTED_ISO2`; send ISO-2 in `country[]`
- [x] Keep `get_lzt_code3()` for display / tolerant client-side checks
- [x] Map spam codes: -3 = real spam, -4 = geo block (keep), -1/None = unknown, 0 = clean, >0 = blocked
- [x] Update docstrings + fallback log to ISO-2

## Tests
- [x] `tests/test_lzt_errors.py` -> 54 checks (added spam-code mapping + ISO-2 conversion)
- [x] `tests/test_search_settings.py` -> expects `country[]=IN`
- [x] `tests/test_lzt_spec.py` -> passes
- [x] `compileall` clean

## Live end-to-end (real bot code, token never printed)
- [x] India nonspam -> 40 items, total 55,885, 0 spam, no fallback
- [x] USA nonspam -> 40 items, total 38,612, 0 spam
- [x] Iran nonspam -> 39 items, total 1,566, 0 spam
- [x] India spam -> 40 items, total 30,755, 15 spam

## Git
- [x] Branch, commit, push, PR, merge to main
