# Task: Fix LZT live search + Good/Cheap logic + admin panel controls

## 1. Analysis
- [x] Read screenshots (LZT API bot)
- [x] Clone repo & inspect utils/lzt.py, plugins/buy.py, admin panel
- [x] Verify official LZT API params (spam=yes/no/nomatter, order_by enum)

## 2. Search settings module
- [x] Create utils/search_settings.py (defaults + getters/setters + mode resolver)

## 3. Fix live search
- [x] Remove blocking balance lookup from search_items
- [x] Raise search timeout / configurable pages / price range / sort
- [x] Strict client-side spam filter for Good vs Cheap
- [x] Remember per-country totals so live counts appear

## 4. Admin panel
- [x] Add "Search & Quality Settings" page
- [x] Wire buttons/actions (live toggle, good/cheap filters, both-cheap, sort, results, pages, price range, reset)
- [x] Add button to admin main panel

## 5. Buy flow
- [x] Use settings in show_years / process_purchase
- [x] Hide misleading (0) counts in country picker

## 6. Verify & push
- [x] Run existing tests + new tests
- [x] Syntax check all changed files
- [x] Commit on new branch, push, open PR (merged #16)
