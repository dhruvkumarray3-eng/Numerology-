# LZT search: real-key diagnosis + actionable errors

## Diagnosis with the live token
- [x] Token is structurally valid (RS512, exp 2031, market scope present)
- [x] LZT returns 401 "Invalid or expired access token" — identical to a bogus token
- [x] Country resolution is fine: "Usa" -> USA (supported enum)
- [x] Conclusion: the token is revoked/regenerated, not a code bug

## Code changes
- [x] `utils/lzt.py`: `check_connection()` rewritten — /me first, 30s timeout,
      actionable 401/402/403/429 messages, shows user + balance on success
- [x] `utils/lzt.py`: `/telegram` 401/403 message now explains token regeneration
- [x] `plugins/buy.py`: new `_lzt_key_invalid_card` — an expired key no longer
      renders as "No live accounts found"
- [x] `plugins/admin_actions.py`: "Set API Key" validates the token immediately
      and reports the verdict in chat
- [x] `main.py`: boot-time LZT self-check logged to Railway/Render logs

## Verification
- [x] Live run of `check_connection()` with the real key -> clear 401 guidance
- [x] `tests/test_lzt_spec.py` + `tests/test_search_settings.py` pass
- [x] `compileall` clean, no secret in the diff

## Git
- [ ] Commit on new branch, push, PR, merge
