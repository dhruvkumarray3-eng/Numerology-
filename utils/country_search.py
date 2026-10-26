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


def country_matches(query, *values):
    """True when ``query`` refers to any of the supplied country values.

    ``values`` may be provider codes ("india", "91", "IN"), display names
    ("Japan") or ISO-3 codes ("JPN").
    """
    raw = str(query or "").strip()
    if not raw:
        return False

    resolved = resolve_country(raw)
    q_key = _normalise(raw)

    for value in values:
        if value is None:
            continue
        v_raw = str(value).strip()
        if not v_raw:
            continue
        v_key = _normalise(v_raw)

        # Direct substring either way (covers "india" vs "India")
        if q_key and v_key and (q_key in v_key or v_key in q_key):
            return True

        # Same country via ISO resolution
        if resolved:
            v_iso = _value_iso2(v_raw)
            if v_iso and v_iso == resolved["iso2"]:
                return True

        # Dial-code comparison
        q_digits = re.sub(r"\D", "", raw)
        v_digits = re.sub(r"\D", "", v_raw)
        if q_digits and v_digits and q_digits == v_digits:
            return True

    return False


def search_country_dicts(countries, query):
    """Filter a list of ``{"code", "name", ...}`` dicts by a free-text query."""
    if not query:
        return list(countries or [])
    out = []
    for c in countries or []:
        if country_matches(query, c.get("code"), c.get("name"), c.get("iso3")):
            out.append(c)
    return out


def search_country_names(names, query):
    """Filter an iterable of country-name strings by a free-text query."""
    if not query:
        return list(names or [])
    return [n for n in (names or []) if country_matches(query, n)]


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
