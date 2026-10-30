"""Universal country resolver + fuzzy search.

Every product panel (WhatsApp, TG Number Change, All Apps OTP, the LZT
"Good Quality" / "Cheap phishing" servers, manual/basic Telegram accounts)
uses this module so a user can type **any** of these and always get the same
country back:

    India        india        IN        IND        +91        91
    Japan        japan        JP        JPN        +81        81
    USA          us / usa     US        USA        +1         1
    UK / England / Britain    GB        GBR        +44        44

The old per-panel filters only did a naive lowercase substring test against
the provider's raw ``code``/``name`` fields, which is why typing ``Japan``
returned "No country found" even though the panel was connected.  This module
resolves the query to an ISO-3166 alpha-2 country first and only then matches
the panel's rows against it.
"""

from __future__ import annotations

import re

from utils.flags import _COUNTRIES, _DIAL, _ALPHA3, _normalise

# ISO-2 -> canonical English name
ISO2_TO_NAME = {iso: names[0] for iso, names in _COUNTRIES.items()}

# Extra human aliases that are not in the ISO table.
_ALIASES = {
    "uk": "gb", "england": "gb", "britain": "gb", "greatbritain": "gb",
    "unitedkingdom": "gb", "unitedkingdomofgreatbritain": "gb",
    "usa": "us", "us": "us", "america": "us", "unitedstates": "us",
    "unitedstatesofamerica": "us", "states": "us",
    "uae": "ae", "emirates": "ae", "dubai": "ae", "abudhabi": "ae",
    "southkorea": "kr", "korea": "kr", "republicofkorea": "kr",
    "northkorea": "kp", "russia": "ru", "russianfederation": "ru",
    "czechia": "cz", "czechrepublic": "cz",
    "ivorycoast": "ci", "cotedivoire": "ci",
    "drcongo": "cd", "democraticrepublicofthecongo": "cd", "congokinshasa": "cd",
    "congo": "cg", "republicofthecongo": "cg",
    "vietnam": "vn", "viet nam": "vn", "burma": "mm", "myanmar": "mm",
    "holland": "nl", "netherlands": "nl",
    "turkiye": "tr", "türkiye": "tr", "turkey": "tr",
    "macedonia": "mk", "northmacedonia": "mk",
    "swaziland": "sz", "eswatini": "sz",
    "capeverde": "cv", "caboverde": "cv",
    "easttimor": "tl", "timorleste": "tl",
    "saudiarabia": "sa", "ksa": "sa",
    "srilanka": "lk", "ceylon": "lk",
    "bangladesh": "bd", "pakistan": "pk",
    "saotomeandprincipe": "st", "saotome": "st",
}

# alpha-3 -> alpha-2 (flags only ships a subset, we extend it from lzt lazily)
ISO3_TO_ISO2 = {a3: a2 for a3, a2 in _ALPHA3.items()}


def _extend_iso3():
    """Pull the full alpha-3 table from utils.lzt without a hard import cycle."""
    try:
        from utils.lzt import ISO2_TO_ISO3 as _full
    except Exception:
        return
    for a2, a3 in _full.items():
        ISO3_TO_ISO2.setdefault(str(a3).lower(), str(a2).lower())


_extend_iso3()
ISO2_TO_ISO3 = {a2: a3.upper() for a3, a2 in ISO3_TO_ISO2.items()}


def _strip_leading_noise(value: str) -> str:
    return re.sub(r"^[^A-Za-z0-9+]+", "", str(value or "")).strip()


def _name_index():
    """normalised name/alias -> iso2 (built once)."""
    global _NAME_INDEX
    try:
        return _NAME_INDEX
    except NameError:
        pass
    idx = {}
    for iso2, names in _COUNTRIES.items():
        idx[_normalise(iso2)] = iso2
        for name in names:
            idx[_normalise(name)] = iso2
            short = _normalise(re.sub(r"\b(republic|islands?|and|of)\b", " ", name, flags=re.I))
            if short:
                idx.setdefault(short, iso2)
    for alias, iso2 in _ALIASES.items():
        idx.setdefault(_normalise(alias), iso2)
    _NAME_INDEX = idx
    return idx


def resolve_country(query):
    """Resolve any country-ish string to a dict.

    Returns ``{"iso2", "iso3", "name", "dial", "flag"}`` or ``None``.
    """
    raw = _strip_leading_noise(query)
    if not raw:
        return None
    key = _normalise(raw)

    iso2 = None

    # 1. Dial code: "+91", "91", "0091"
    digits = re.sub(r"\D", "", raw)
    if digits and (raw.lstrip().startswith("+") or digits == key or key.isdigit()):
        cand = digits
        if cand.startswith("00") and cand[2:] in _DIAL:
            cand = cand[2:]
        if cand in _DIAL:
            iso2 = _DIAL[cand]

    # 2. ISO-2
    if not iso2 and len(key) == 2 and key in _COUNTRIES:
        iso2 = key

    # 3. ISO-3
    if not iso2 and len(key) == 3 and key in ISO3_TO_ISO2:
        iso2 = ISO3_TO_ISO2[key]

    idx = _name_index()

    # 4. Exact name / alias
    if not iso2:
        iso2 = idx.get(key)

    # 5. Substring match (longest name wins so "south africa" beats "africa")
    if not iso2 and len(key) >= 3:
        best = None
        for name, cand in idx.items():
            if len(name) >= 3 and (name in key or key in name):
                if best is None or len(name) > len(best[0]):
                    best = (name, cand)
        if best:
            iso2 = best[1]

    if not iso2 or iso2 not in _COUNTRIES:
        return None

    dial = next((d for d, i in _DIAL.items() if i == iso2), None)
    return {
        "iso2": iso2,
        "iso3": ISO2_TO_ISO3.get(iso2),
        "name": ISO2_TO_NAME.get(iso2, iso2.upper()),
        "dial": dial,
        "flag": "".join(chr(0x1F1E6 + ord(ch) - ord("a")) for ch in iso2),
    }


def _value_iso2(value):
    """Best-effort ISO-2 for a value coming from a provider row."""
    if not value:
        return None
    resolved = resolve_country(value)
    return resolved["iso2"] if resolved else None


# Scoring tiers.  Higher is a better match; 0 means "no match".
_SCORE_EXACT = 100      # query == name / code / iso2 / iso3
_SCORE_PREFIX = 80      # name starts with the query ("jap" -> Japan)
_SCORE_WORD = 60        # a word inside the name starts with the query
_SCORE_SUBSTR = 40      # query appears anywhere in the name
_SCORE_FUZZY = 25       # typo tolerance ("jpan" -> Japan)
_SCORE_ISO = 90         # query resolves to the same country as the value


def _fuzzy_ratio(a, b):
    """Similarity in 0..1 without importing difflib at module import time."""
    try:
        from difflib import SequenceMatcher
        return SequenceMatcher(None, a, b).ratio()
    except Exception:
        return 0.0


# Filler words users type around a country name.  They carry no matching
# value, so stripping them lets "india number" / "buy usa sim" resolve to the
# country instead of failing the substring test.
_NOISE_WORDS = frozenset({
    "number", "numbers", "num", "sim", "sims", "card", "cards", "account",
    "accounts", "acc", "phone", "mobile", "virtual", "code", "otp", "sms",
    "verification", "verify", "for", "the", "a", "an", "of", "in", "to",
    "buy", "get", "any", "all", "new", "fresh", "cheap", "best",
})


def _tokens(value):
    """Lowercase word tokens (keeps spaces, unlike ``_normalise``)."""
    return [t for t in re.split(r"[^a-z0-9]+", str(value or "").lower()) if t]


def country_score(query, *values):
    """How well ``query`` matches any of ``values`` (0 = no match).

    ``values`` may be provider codes ("india", "91", "IN"), display names
    ("Japan") or ISO-3 codes ("JPN").  The score lets callers *rank* results
    instead of just filtering them, so typing "in" shows India first and does
    not bury it under "Indonesia"/"Finland".
    """
    raw = str(query or "").strip()
    if not raw:
        return 0

    resolved = resolve_country(raw)
    q_key = _normalise(raw)
    q_digits = re.sub(r"\D", "", raw)
    # Cleaned query: filler words removed, e.g. "india number" -> "india".
    q_tokens = [t for t in _tokens(raw) if t not in _NOISE_WORDS]
    q_clean = _normalise(" ".join(q_tokens)) or q_key
    best = 0

    for value in values:
        if value is None:
            continue
        v_raw = str(value).strip()
        if not v_raw:
            continue
        v_key = _normalise(v_raw)
        if not v_key:
            continue

        # 1. Exact hit on any representation.
        if q_key == v_key:
            best = max(best, _SCORE_EXACT)

        # 2. Same country via ISO resolution (covers "UK" -> "United Kingdom").
        if resolved:
            v_iso = _value_iso2(v_raw)
            if v_iso and v_iso == resolved["iso2"]:
                best = max(best, _SCORE_ISO)

        # 3. Prefix of the whole name ("jap" -> "Japan").
        if v_key.startswith(q_key):
            best = max(best, _SCORE_PREFIX)

        # 4. Any word inside the name starts with the query
        #    ("korea" -> "South Korea", "guinea" -> "Papua New Guinea").
        if any(word.startswith(q_key) for word in v_key.split()):
            best = max(best, _SCORE_WORD)

        # 5. Plain substring either way ("india" vs "India").  Skipped for
        #    1-2 character queries: "in" is inside "k-i-n-gdom" and "us" is
        #    inside "a-u-s-tralia", which used to bury the real answer under
        #    noise.  Short queries must match a prefix or a word start instead.
        if len(q_key) >= 3 and len(v_key) >= 3 and (
                q_key in v_key or v_key in q_key):
            best = max(best, _SCORE_SUBSTR)

        # 6. Dial-code comparison ("+91" / "91").
        if q_digits and len(q_digits) <= 4:
            v_digits = re.sub(r"\D", "", v_raw)
            if v_digits and q_digits == v_digits:
                best = max(best, _SCORE_EXACT)

        # 6b. Cleaned query (filler words removed) as an alternative target,
        #     so "india number" / "buy usa sim" still resolve.
        if q_clean != q_key and len(q_clean) >= 3:
            if v_key.startswith(q_clean):
                best = max(best, _SCORE_PREFIX)
            elif q_clean in v_key or v_key in q_clean:
                best = max(best, _SCORE_SUBSTR)

        # 6c. Token-set match: every meaningful query word appears as a token
        #     prefix in the value ("south korea", "united arab emirates").
        if len(q_tokens) >= 2:
            v_tokens = _tokens(v_raw)
            if all(any(vt.startswith(qt) for vt in v_tokens) for qt in q_tokens):
                best = max(best, _SCORE_WORD + 5)

        # 7. Typo tolerance, only for reasonably long queries so that "us"
        #    does not fuzzy-match "AU".
        if (len(q_key) >= 4 and len(v_key) >= 4
                and q_key[0] == v_key[0]):
            ratio = _fuzzy_ratio(q_key, v_key)
            if ratio >= 0.8:
                best = max(best, _SCORE_FUZZY)

    return best


def country_matches(query, *values):
    """True when ``query`` refers to any of the supplied country values."""
    return country_score(query, *values) > 0


def search_country_dicts(countries, query):
    """Filter **and rank** a list of ``{"code", "name", ...}`` dicts.

    Results are ordered best-match-first so "in" puts India above Indonesia and
    "us" puts the United States above Australia.  Ties keep the original order.
    """
    if not query:
        return list(countries or [])

    scored = []
    for idx, c in enumerate(countries or []):
        score = country_score(
            query, c.get("code"), c.get("name"), c.get("iso3"),
            c.get("iso2"), c.get("dial"),
        )
        if score > 0:
            scored.append((score, idx, c))

    if not scored:
        return []
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [c for _, _, c in scored]


def search_country_names(names, query):
    """Filter and rank an iterable of country-name strings."""
    if not query:
        return list(names or [])
    scored = []
    for idx, n in enumerate(names or []):
        score = country_score(query, n)
        if score > 0:
            scored.append((score, idx, n))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [n for _, _, n in scored]


def all_countries():
    """Every known country as ``{"iso2", "iso3", "name", "dial"}``."""
    out = []
    for iso2, names in _COUNTRIES.items():
        out.append({
            "iso2": iso2,
            "iso3": ISO2_TO_ISO3.get(iso2),
            "name": names[0],
            "dial": next((d for d, i in _DIAL.items() if i == iso2), None),
        })
    return sorted(out, key=lambda c: c["name"])


def canonical_name(value):
    """Return the canonical English name for any country-ish value."""
    resolved = resolve_country(value)
    return resolved["name"] if resolved else None
