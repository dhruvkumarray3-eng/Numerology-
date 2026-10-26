# Todo — Fix "live stock still not showing" (round 4)

## Diagnosis
- [x] Confirm auth is fine (screenshots: "Connected to LZT Market!", balance 413 USD)
- [x] Verify `country[]`, `order_by`, `spam`, `allow_geo_spamblock`, `after` against official spec
- [x] Find root cause: LZT 403 is used for BOTH "bad token" and "no Market API access
      (200 sympathies / paid subscription)"; bot reported both as "API key invalid"
- [x] Find second cause: "strict spam" dropped every item with `telegram_spam_block == -1`
      (unknown), emptying whole countries

## Fixes
- [x] Add `classify_lzt_error()` -> auth / access / rate / bad / server / unknown
- [x] Store `last_error_kind` + `last_body`; log status, totalItems, items, sample item
- [x] `check_connection()` 403 branch now distinguishes access vs scope
- [x] New `_lzt_access_card()` with "Buy Market Access" button + honest explanation
- [x] Route empty state by error kind (access / auth / no-stock)
- [x] Stop dropping unknown-spam items (keep API-side spam=no/spam=yes as source of truth)
- [x] Country-filter fallback: retry without `country[]`, filter client-side
- [x] Default max_pages 4 -> 2, larger hard timeout budget
- [x] Admin "Test / Balance" shows HTTP status, totalItems, error kind
- [x] Tests: `tests/test_lzt_errors.py` (14 checks) + all existing suites pass
- [x] compileall clean

## Git
- [x] New branch `fix/lzt-market-access-and-filters`
- [ ] Commit + push
- [ ] Open PR + merge into main
