"""Country flag resolver.

The OTP panels receive country identifiers in many shapes:

    * ISO-2 codes          -> "in", "us", "gb"
    * ISO-3 codes          -> "ind", "usa", "gbr"
    * TemporaSMS slugs     -> "india", "england", "usa", "southafrica"
    * Display names        -> "United Kingdom", "Cote d'Ivoire"
    * Emoji-prefixed names -> "India" with a leading flag

`flag_for()` normalises all of them into a real flag emoji so every country
button in the bot shows its flag. Falls back to a globe only for genuinely
unknown values.
"""

from __future__ import annotations

import re

# ISO-3166 alpha-2 -> (English name, extra aliases)
#
# This table covers the full ISO-3166-1 alpha-2 set (249 officially assigned
# codes) so every country is selectable in the bot and every one of them can
# be sent to the LZT `country[]` filter, which accepts any valid alpha-2 code.
_COUNTRIES = {
    # -- territories / dependencies that were previously missing -------------
    "ag": ("Antigua and Barbuda",),
    "ai": ("Anguilla",),
    "aq": ("Antarctica",),
    "as": ("American Samoa",),
    "aw": ("Aruba",),
    "ax": ("Aland Islands",),
    "bl": ("Saint Barthelemy",),
    "bm": ("Bermuda",),
    "bq": ("Caribbean Netherlands", "Bonaire"),
    "bv": ("Bouvet Island",),
    "cc": ("Cocos Islands", "Keeling Islands"),
    "ck": ("Cook Islands",),
    "cw": ("Curacao",),
    "cx": ("Christmas Island",),
    "eh": ("Western Sahara",),
    "fk": ("Falkland Islands",),
    "fo": ("Faroe Islands",),
    "gf": ("French Guiana",),
    "gg": ("Guernsey",),
    "gi": ("Gibraltar",),
    "gl": ("Greenland",),
    "gp": ("Guadeloupe",),
    "gs": ("South Georgia",),
    "gu": ("Guam",),
    "hm": ("Heard Island",),
    "im": ("Isle of Man",),
    "io": ("British Indian Ocean Territory",),
    "je": ("Jersey",),
    "ky": ("Cayman Islands",),
    "mf": ("Saint Martin",),
    "mp": ("Northern Mariana Islands",),
    "mq": ("Martinique",),
    "ms": ("Montserrat",),
    "nc": ("New Caledonia",),
    "nf": ("Norfolk Island",),
    "nu": ("Niue",),
    "pf": ("French Polynesia",),
    "pm": ("Saint Pierre and Miquelon",),
    "pn": ("Pitcairn Islands",),
    "re": ("Reunion",),
    "sh": ("Saint Helena",),
    "sj": ("Svalbard and Jan Mayen",),
    "sx": ("Sint Maarten",),
    "tc": ("Turks and Caicos Islands",),
    "tf": ("French Southern Territories",),
    "tk": ("Tokelau",),
    "um": ("United States Minor Outlying Islands",),
    "vg": ("British Virgin Islands",),
    "vi": ("US Virgin Islands",),
    "wf": ("Wallis and Futuna",),
    "yt": ("Mayotte",),
    "af": ("Afghanistan",),
    "al": ("Albania",),
    "dz": ("Algeria",),
    "ad": ("Andorra",),
    "ao": ("Angola",),
    "ar": ("Argentina",),
    "am": ("Armenia",),
    "au": ("Australia",),
    "at": ("Austria",),
    "az": ("Azerbaijan",),
    "bs": ("Bahamas",),
    "bh": ("Bahrain",),
    "bd": ("Bangladesh",),
    "bb": ("Barbados",),
    "by": ("Belarus",),
    "be": ("Belgium",),
    "bz": ("Belize",),
    "bj": ("Benin",),
    "bt": ("Bhutan",),
    "bo": ("Bolivia",),
    "ba": ("Bosnia and Herzegovina", "bosnia"),
    "bw": ("Botswana",),
    "br": ("Brazil",),
    "bn": ("Brunei",),
    "bg": ("Bulgaria",),
    "bf": ("Burkina Faso",),
    "bi": ("Burundi",),
    "kh": ("Cambodia",),
    "cm": ("Cameroon",),
    "ca": ("Canada",),
    "cv": ("Cape Verde", "capeverde"),
    "cf": ("Central African Republic",),
    "td": ("Chad",),
    "cl": ("Chile",),
    "cn": ("China",),
    "co": ("Colombia",),
    "km": ("Comoros",),
    "cg": ("Congo",),
    "cd": ("DR Congo", "democraticrepublicofthecongo", "congokinshasa"),
    "cr": ("Costa Rica",),
    "ci": ("Ivory Coast", "cotedivoire"),
    "hr": ("Croatia",),
    "cu": ("Cuba",),
    "cy": ("Cyprus",),
    "cz": ("Czech Republic", "czechia", "czech"),
    "dk": ("Denmark",),
    "dj": ("Djibouti",),
    "dm": ("Dominica",),
    "do": ("Dominican Republic",),
    "ec": ("Ecuador",),
    "eg": ("Egypt",),
    "sv": ("El Salvador",),
    "gq": ("Equatorial Guinea",),
    "er": ("Eritrea",),
    "ee": ("Estonia",),
    "sz": ("Eswatini", "swaziland"),
    "et": ("Ethiopia",),
    "fj": ("Fiji",),
    "fi": ("Finland",),
    "fr": ("France",),
    "ga": ("Gabon",),
    "gm": ("Gambia",),
    "ge": ("Georgia",),
    "de": ("Germany", "deutschland"),
    "gh": ("Ghana",),
    "gr": ("Greece",),
    "gd": ("Grenada",),
    "gt": ("Guatemala",),
    "gn": ("Guinea",),
    "gw": ("Guinea-Bissau",),
    "gy": ("Guyana",),
    "ht": ("Haiti",),
    "hn": ("Honduras",),
    "hk": ("Hong Kong", "hongkong"),
    "hu": ("Hungary",),
    "is": ("Iceland",),
    "in": ("India",),
    "id": ("Indonesia",),
    "ir": ("Iran",),
    "iq": ("Iraq",),
    "ie": ("Ireland",),
    "il": ("Israel",),
    "it": ("Italy",),
    "jm": ("Jamaica",),
    "jp": ("Japan",),
    "jo": ("Jordan",),
    "kz": ("Kazakhstan",),
    "ke": ("Kenya",),
    "ki": ("Kiribati",),
    "kw": ("Kuwait",),
    "kg": ("Kyrgyzstan",),
    "la": ("Laos",),
    "lv": ("Latvia",),
    "lb": ("Lebanon",),
    "ls": ("Lesotho",),
    "lr": ("Liberia",),
    "ly": ("Libya",),
    "li": ("Liechtenstein",),
    "lt": ("Lithuania",),
    "lu": ("Luxembourg",),
    "mo": ("Macau", "macao"),
    "mg": ("Madagascar",),
    "mw": ("Malawi",),
    "my": ("Malaysia",),
    "mv": ("Maldives",),
    "ml": ("Mali",),
    "mt": ("Malta",),
    "mh": ("Marshall Islands",),
    "mr": ("Mauritania",),
    "mu": ("Mauritius",),
    "mx": ("Mexico",),
    "fm": ("Micronesia",),
    "md": ("Moldova",),
    "mc": ("Monaco",),
    "mn": ("Mongolia",),
    "me": ("Montenegro",),
    "ma": ("Morocco",),
    "mz": ("Mozambique",),
    "mm": ("Myanmar", "burma"),
    "na": ("Namibia",),
    "nr": ("Nauru",),
    "np": ("Nepal",),
    "nl": ("Netherlands", "holland"),
    "nz": ("New Zealand", "newzealand"),
    "ni": ("Nicaragua",),
    "ne": ("Niger",),
    "ng": ("Nigeria",),
    "kp": ("North Korea", "northkorea"),
    "mk": ("North Macedonia", "macedonia"),
    "no": ("Norway",),
    "om": ("Oman",),
    "pk": ("Pakistan",),
    "pw": ("Palau",),
    "ps": ("Palestine",),
    "pa": ("Panama",),
    "pg": ("Papua New Guinea", "papuanewguinea"),
    "py": ("Paraguay",),
    "pe": ("Peru",),
    "ph": ("Philippines",),
    "pl": ("Poland",),
    "pt": ("Portugal",),
    "pr": ("Puerto Rico", "puertorico"),
    "qa": ("Qatar",),
    "ro": ("Romania",),
    "ru": ("Russia", "russianfederation"),
    "rw": ("Rwanda",),
    "kn": ("Saint Kitts and Nevis",),
    "lc": ("Saint Lucia",),
    "vc": ("Saint Vincent and the Grenadines",),
    "ws": ("Samoa",),
    "sm": ("San Marino",),
    "st": ("Sao Tome and Principe",),
    "sa": ("Saudi Arabia", "saudiarabia", "ksa"),
    "sn": ("Senegal",),
    "rs": ("Serbia",),
    "sc": ("Seychelles",),
    "sl": ("Sierra Leone",),
    "sg": ("Singapore",),
    "sk": ("Slovakia",),
    "si": ("Slovenia",),
    "sb": ("Solomon Islands",),
    "so": ("Somalia",),
    "za": ("South Africa", "southafrica"),
    "kr": ("South Korea", "southkorea", "korea"),
    "ss": ("South Sudan",),
    "es": ("Spain",),
    "lk": ("Sri Lanka", "srilanka"),
    "sd": ("Sudan",),
    "sr": ("Suriname",),
    "se": ("Sweden",),
    "ch": ("Switzerland",),
    "sy": ("Syria",),
    "tw": ("Taiwan",),
    "tj": ("Tajikistan",),
    "tz": ("Tanzania",),
    "th": ("Thailand",),
    "tl": ("Timor-Leste", "easttimor"),
    "tg": ("Togo",),
    "to": ("Tonga",),
    "tt": ("Trinidad and Tobago",),
    "tn": ("Tunisia",),
    "tr": ("Turkey", "turkiye"),
    "tm": ("Turkmenistan",),
    "tv": ("Tuvalu",),
    "ug": ("Uganda",),
    "ua": ("Ukraine",),
    "ae": ("United Arab Emirates", "uae", "emirates"),
    "gb": ("United Kingdom", "uk", "england", "greatbritain", "britain"),
    "us": ("United States", "usa", "unitedstatesofamerica", "america"),
    "uy": ("Uruguay",),
    "uz": ("Uzbekistan",),
    "vu": ("Vanuatu",),
    "va": ("Vatican City", "vatican"),
    "ve": ("Venezuela",),
    "vn": ("Vietnam", "vietnam"),
    "ye": ("Yemen",),
    "zm": ("Zambia",),
    "zw": ("Zimbabwe",),
}

# ISO-3166 alpha-3 -> alpha-2 (commonly used ones)
_ALPHA3 = {
    "ind": "in", "usa": "us", "gbr": "gb", "rus": "ru", "deu": "de", "ger": "de",
    "fra": "fr", "esp": "es", "ita": "it", "bra": "br", "can": "ca", "aus": "au",
    "idn": "id", "phl": "ph", "vnm": "vn", "ukr": "ua", "kaz": "kz", "pak": "pk",
    "bgd": "bd", "lka": "lk", "npl": "np", "are": "ae", "sau": "sa", "tur": "tr",
    "egy": "eg", "nga": "ng", "ken": "ke", "zaf": "za", "mex": "mx", "arg": "ar",
    "col": "co", "per": "pe", "chl": "cl", "pol": "pl", "rou": "ro", "nld": "nl",
    "bel": "be", "che": "ch", "aut": "at", "swe": "se", "nor": "no", "dnk": "dk",
    "fin": "fi", "irl": "ie", "prt": "pt", "grc": "gr", "cze": "cz", "hun": "hu",
    "tha": "th", "mys": "my", "sgp": "sg", "kor": "kr", "jpn": "jp", "chn": "cn",
    "twn": "tw", "hkg": "hk", "isr": "il", "irq": "iq", "irn": "ir", "geo": "ge",
    "arm": "am", "aze": "az", "uzb": "uz", "tjk": "tj", "tkm": "tm", "kgz": "kg",
    "mng": "mn", "mmr": "mm", "khm": "kh", "lao": "la", "brn": "bn",
}


# Common international dial codes -> ISO-2 (used when a "+91" style value
# is passed instead of a country name).
_DIAL = {
    "1": "us", "7": "ru", "20": "eg", "27": "za", "30": "gr", "31": "nl",
    "32": "be", "33": "fr", "34": "es", "36": "hu", "39": "it", "40": "ro",
    "41": "ch", "43": "at", "44": "gb", "45": "dk", "46": "se", "47": "no",
    "48": "pl", "49": "de", "51": "pe", "52": "mx", "53": "cu", "54": "ar",
    "55": "br", "56": "cl", "57": "co", "58": "ve", "60": "my", "61": "au",
    "62": "id", "63": "ph", "64": "nz", "65": "sg", "66": "th", "81": "jp",
    "82": "kr", "84": "vn", "86": "cn", "90": "tr", "91": "in", "92": "pk",
    "93": "af", "94": "lk", "95": "mm", "98": "ir", "211": "ss", "212": "ma",
    "213": "dz", "216": "tn", "218": "ly", "220": "gm", "221": "sn",
    "222": "mr", "223": "ml", "224": "gn", "225": "ci", "226": "bf",
    "227": "ne", "228": "tg", "229": "bj", "230": "mu", "231": "lr",
    "232": "sl", "233": "gh", "234": "ng", "235": "td", "236": "cf",
    "237": "cm", "238": "cv", "239": "st", "240": "gq", "241": "ga",
    "242": "cg", "243": "cd", "244": "ao", "245": "gw", "246": "io",
    "248": "sc", "249": "sd", "250": "rw", "251": "et", "252": "so",
    "253": "dj", "254": "ke", "255": "tz", "256": "ug", "257": "bi",
    "258": "mz", "260": "zm", "261": "mg", "262": "re", "263": "zw",
    "264": "na", "265": "mw", "266": "ls", "267": "bw", "268": "sz",
    "269": "km", "290": "sh", "291": "er", "297": "aw", "298": "fo",
    "299": "gl", "350": "gi", "351": "pt", "352": "lu", "353": "ie",
    "354": "is", "355": "al", "356": "mt", "357": "cy", "358": "fi",
    "359": "bg", "370": "lt", "371": "lv", "372": "ee", "373": "md",
    "374": "am", "375": "by", "376": "ad", "377": "mc", "378": "sm",
    "380": "ua", "381": "rs", "382": "me", "383": "xk", "385": "hr",
    "386": "si", "387": "ba", "389": "mk", "420": "cz", "421": "sk",
    "423": "li", "501": "bz", "502": "gt", "503": "sv", "504": "hn",
    "505": "ni", "506": "cr", "507": "pa", "509": "ht", "591": "bo",
    "592": "gy", "593": "ec", "595": "py", "597": "sr", "598": "uy",
    "673": "bn", "674": "nr", "675": "pg", "676": "to", "677": "sb",
    "678": "vu", "679": "fj", "680": "pw", "685": "ws", "686": "ki",
    "687": "nc", "688": "tv", "689": "pf", "690": "tk", "691": "fm",
    "692": "mh", "850": "kp", "852": "hk", "853": "mo", "855": "kh",
    "856": "la", "880": "bd", "886": "tw", "960": "mv", "961": "lb",
    "962": "jo", "963": "sy", "964": "iq", "965": "kw", "966": "sa",
    "967": "ye", "968": "om", "970": "ps", "971": "ae", "972": "il",
    "973": "bh", "974": "qa", "975": "bt", "976": "mn", "977": "np",
    "992": "tj", "993": "tm", "994": "az", "995": "ge", "996": "kg",
    "998": "uz",
}


def _normalise(value: str) -> str:
    """Lowercase and strip everything except latin letters/digits."""
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _emoji(iso2: str) -> str:
    return "".join(chr(0x1F1E6 + ord(ch) - ord("a")) for ch in iso2.lower())


# Build the name -> iso2 index once.
_NAME_INDEX = {}
for _iso, _names in _COUNTRIES.items():
    _NAME_INDEX[_iso] = _iso
    for _name in _names:
        _NAME_INDEX[_normalise(_name)] = _iso
        _short = _normalise(re.sub(r"\b(republic|islands?|and)\b", " ", _name, flags=re.I))
        if _short:
            _NAME_INDEX.setdefault(_short, _iso)


def flag_for(value) -> str:
    """Return a flag emoji for an ISO code, slug, or country name."""
    raw = str(value or "").strip()
    if not raw:
        return "\U0001F30D"

    # 1. Already a flag emoji (two regional indicator symbols)
    if len(raw) >= 2 and all(0x1F1E6 <= ord(ch) <= 0x1F1FF for ch in raw[:2]):
        return raw[:2]

    # 2. Strip leading emoji / decoration, keep letters and digits
    cleaned = re.sub(r"^[^A-Za-z0-9]+", "", raw)
    key = _normalise(cleaned)

    # 3. Exact ISO-2 / ISO-3
    if len(key) == 2 and key in _COUNTRIES:
        return _emoji(key)
    if key in _ALPHA3:
        return _emoji(_ALPHA3[key])

    # 3b. Dial code such as "+91" or "91"
    if key.isdigit():
        if key in _DIAL:
            return _emoji(_DIAL[key])
        # Tolerate leading international prefix "00"
        if key.startswith("00") and key[2:] in _DIAL:
            return _emoji(_DIAL[key[2:]])

    # 4. Name / slug lookup
    iso = _NAME_INDEX.get(key)
    if iso:
        return _emoji(iso)

    # 5. Try removing trailing words such as "number", "virtual", "sms"
    for suffix in ("virtualnumber", "number", "virtual", "sms", "otp", "account"):
        if key.endswith(suffix):
            iso = _NAME_INDEX.get(key[: -len(suffix)])
            if iso:
                return _emoji(iso)

    # 6. Substring fallback (longest name first so "south africa" wins)
    if len(key) >= 4:
        best = None
        for name, iso2 in _NAME_INDEX.items():
            if len(name) >= 4 and (name in key or key in name):
                if best is None or len(name) > len(best[0]):
                    best = (name, iso2)
        if best:
            return _emoji(best[1])

    return "\U0001F30D"


def clean_name(value) -> str:
    """Strip a leading flag/emoji and trailing noise from a country name."""
    name = str(value or "").strip()
    while name and ord(name[0]) > 0x2000:
        name = name[1:].strip()
    # Remove trailing provider noise like "virtualnumber", "number", "sms".
    name = re.sub(
        r"\s*(virtualnumber|virtual\s*number|number|virtual|sms|otp|account)\s*$",
        "",
        name,
        flags=re.I,
    ).strip()
    return name or "Unknown"
