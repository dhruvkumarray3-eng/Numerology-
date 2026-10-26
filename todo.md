# All-Countries LZT Fix (Round 7)

## Problem
- India/USA worked after round 6, but 44 countries were silently skipped
- `country[]` was only sent when the code was in a hand-maintained whitelist
- Country picker only had 198 of the 249 ISO-3166 countries

## Diagnosis (live-verified)
- [x] LZT accepts **any** valid ISO-2 code: KR / UZ / YE / AF / PG all return stock
- [x] Bogus code (ZZ) just returns 0 — no error, no whitelist needed
- [x] So the whitelist gate was the only blocker

## Fixes
- [x] Removed the whitelist gate — `country[]` is now sent for every resolvable country
- [x] `utils/flags.py`: added the 51 missing ISO-3166 codes -> 249 countries in the picker
- [x] `utils/lzt.py`: `ISO2_TO_ISO3` expanded 176 -> 249 (client-side checks cover everything)
- [x] `LZT_SUPPORTED_ISO2` now derived from the full map (informational only)
- [x] `get_lzt_code2()` handles name / ISO-2 / ISO-3 / dial code

## Tests
- [x] `tests/test_lzt_errors.py` -> 48 checks, incl. "no country left without ISO-2"
- [x] `tests/test_search_settings.py`, `tests/test_lzt_spec.py` green
- [x] `compileall` clean

## Live verification
- [x] 10/10 previously-broken countries now return stock (KR, UZ, YE, AF, PG, GL, BM, RE, GU, JE)
- [ ] Full 249-country sweep

## Git
- [ ] Branch, commit, push, PR, merge to main
