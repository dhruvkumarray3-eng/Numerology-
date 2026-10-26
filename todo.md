# Fix: LZT search still empty for USA (round 2)

## Root causes found in official LZT OpenAPI spec
- [x] Per-request timeout was 20s; LZT docs recommend 300s+ for category search
- [x] Missing `allow_geo_spamblock` param -> `spam=no` hid geo-spam-blocked stock
- [x] No fallback when a filtered search returned 0 items
- [x] Confirm `USA` is a supported ISO-3 code (it is)

## Code changes
- [x] `utils/lzt.py`: request timeout 75s via `aiohttp.ClientTimeout`
- [x] `utils/lzt.py`: send `allow_geo_spamblock=true` for `spam=no` searches
- [x] `utils/lzt.py`: auto-fallback retry (relax spam/price, 2 pages max)
- [x] `utils/lzt.py`: generous outer budget tied to per-request timeout
- [x] `utils/search_settings.py`: `allow_geo_spam()` + `auto_fallback()` + defaults
- [x] `plugins/admin_actions.py`: two new toggles on Search & Quality page

## Verification
- [x] `tests/test_search_settings.py` extended (geo-spam + fallback) -> all pass
- [x] `tests/test_lzt_spec.py` -> all pass
- [x] `compileall utils plugins tests` -> clean

## Git
- [x] Commit on new branch, push, open + merge PR
