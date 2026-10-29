"""Lightweight translation layer for the vendor bot.

The bot stores a per-user language code in the ``users`` table (see
``database.get_user_language`` / ``set_user_language``).  Every user-facing
screen can call :func:`t` to render a label in the user's chosen language and
silently fall back to English when a key (or the whole language) is missing.

Design goals
------------
* **Never raise.**  A translation lookup must never be able to crash a handler,
  so every DB access and every ``str.format`` call is wrapped defensively.
* **Additive.**  Unknown languages simply reuse the English table, so adding a
  new language later only means adding one dict here.
* **Cheap.**  No heavy imports at module load time; ``database`` is imported
  lazily inside :func:`get_lang`.
"""

from __future__ import annotations

DEFAULT_LANG = "en"

# ---------------------------------------------------------------------------
# Translation tables.  Keep keys identical across languages so a missing key
# in one language cleanly falls back to English.
# ---------------------------------------------------------------------------
TRANSLATIONS = {
    "en": {
        "settings_title": "Settings",
        "settings_note": "Choose how prices and language are shown to you.",
        "currency": "Currency",
        "language": "Language",
        "prices_note": "INR shows ₹ and USDT together. USDT shows USDT only.",
        "back": "Back",
        "profile_title": "User Profile",
        "user_id": "User ID",
        "balance": "Balance",
        "deposited": "Deposited",
        "referred_users": "Referred Users",
        "joined": "Joined",
        "referral_link": "Your Referral Link",
        "share_note": "Share this link with your friends to earn bonuses!",
        "stats_title": "My Statistics",
        "accounts_bought": "Accounts Bought",
        "referrals": "Referrals",
        "total_spent": "Total Spent",
        "total_deposited": "Total Deposited",
        "view_purchases": "View Purchase Logs",
        "referral_logs": "Referral Logs",
        "level": "Level",
        "next_tier": "Next Tier",
        "more_needed": "{amount} more",
        "deposit_vs_spend": "Deposits vs Spend",
        "max_level": "Maximum level reached!",
        "dashboard_balance": "Balance",
        "dashboard_level": "VIP",
        "support": "Support",
        "owner": "Owner",
        "currency_set": "Currency updated to {name}.",
        "language_set": "Language updated to {name}.",
        "unsupported_currency": "That currency is not supported.",
        "unsupported_language": "That language is not supported.",
        "level_bronze": "Bronze",
        "level_silver": "Silver",
        "level_gold": "Gold",
        "level_platinum": "Platinum",
        "level_diamond": "Diamond",
    },
    "hinglish": {
        "settings_title": "Settings",
        "settings_note": "Chuno ki price aur language kaise dikhe.",
        "currency": "Currency",
        "language": "Language",
        "prices_note": "INR me ₹ aur USDT dono dikhte hain. USDT me sirf USDT.",
        "back": "Wapas",
        "profile_title": "User Profile",
        "user_id": "User ID",
        "balance": "Balance",
        "deposited": "Deposit",
        "referred_users": "Referred Users",
        "joined": "Joined",
        "referral_link": "Aapka Referral Link",
        "share_note": "Ye link dosto ko bhejo aur bonus kamao!",
        "stats_title": "Meri Statistics",
        "accounts_bought": "Accounts Kharide",
        "referrals": "Referrals",
        "total_spent": "Total Kharch",
        "total_deposited": "Total Deposit",
        "view_purchases": "Purchase Logs Dekho",
        "referral_logs": "Referral Logs",
        "level": "Level",
        "next_tier": "Agla Tier",
        "more_needed": "{amount} aur chahiye",
        "deposit_vs_spend": "Deposit vs Kharch",
        "max_level": "Maximum level aa gaya!",
        "dashboard_balance": "Balance",
        "dashboard_level": "VIP",
        "support": "Support",
        "owner": "Owner",
        "currency_set": "Currency {name} set ho gayi.",
        "language_set": "Language {name} set ho gayi.",
        "unsupported_currency": "Ye currency support nahi hai.",
        "unsupported_language": "Ye language support nahi hai.",
        "level_bronze": "Bronze",
        "level_silver": "Silver",
        "level_gold": "Gold",
        "level_platinum": "Platinum",
        "level_diamond": "Diamond",
    },
    "hi": {
        "settings_title": "सेटिंग्स",
        "settings_note": "चुनें कि कीमत और भाषा कैसे दिखे।",
        "currency": "मुद्रा",
        "language": "भाषा",
        "prices_note": "INR में ₹ और USDT दोनों दिखते हैं। USDT में केवल USDT।",
        "back": "वापस",
        "profile_title": "उपयोगकर्ता प्रोफ़ाइल",
        "user_id": "यूज़र आईडी",
        "balance": "बैलेंस",
        "deposited": "जमा",
        "referred_users": "रेफ़र किए गए उपयोगकर्ता",
        "joined": "जुड़े",
        "referral_link": "आपका रेफ़रल लिंक",
        "share_note": "यह लिंक दोस्तों को भेजें और बोनस कमाएँ!",
        "stats_title": "मेरी आंकड़े",
        "accounts_bought": "खरीदे गए अकाउंट",
        "referrals": "रेफ़रल",
        "total_spent": "कुल खर्च",
        "total_deposited": "कुल जमा",
        "view_purchases": "खरीद लॉग देखें",
        "referral_logs": "रेफ़रल लॉग",
        "level": "स्तर",
        "next_tier": "अगला स्तर",
        "more_needed": "{amount} और चाहिए",
        "deposit_vs_spend": "जमा बनाम खर्च",
        "max_level": "अधिकतम स्तर पूरा!",
        "dashboard_balance": "बैलेंस",
        "dashboard_level": "VIP",
        "support": "सहायता",
        "owner": "मालिक",
        "currency_set": "मुद्रा {name} पर सेट हुई।",
        "language_set": "भाषा {name} पर सेट हुई।",
        "unsupported_currency": "यह मुद्रा समर्थित नहीं है।",
        "unsupported_language": "यह भाषा समर्थित नहीं है।",
        "level_bronze": "कांस्य",
        "level_silver": "रजत",
        "level_gold": "स्वर्ण",
        "level_platinum": "प्लेटिनम",
        "level_diamond": "हीरा",
    },
    "ru": {
        "settings_title": "Настройки",
        "settings_note": "Выберите, как показывать цены и язык.",
        "currency": "Валюта",
        "language": "Язык",
        "prices_note": "INR показывает ₹ и USDT вместе. USDT — только USDT.",
        "back": "Назад",
        "profile_title": "Профиль",
        "user_id": "ID пользователя",
        "balance": "Баланс",
        "deposited": "Пополнено",
        "referred_users": "Приглашённые",
        "joined": "Регистрация",
        "referral_link": "Ваша реферальная ссылка",
        "share_note": "Поделитесь ссылкой с друзьями и получайте бонусы!",
        "stats_title": "Моя статистика",
        "accounts_bought": "Куплено аккаунтов",
        "referrals": "Рефералы",
        "total_spent": "Всего потрачено",
        "total_deposited": "Всего пополнено",
        "view_purchases": "История покупок",
        "referral_logs": "Реферальные логи",
        "level": "Уровень",
        "next_tier": "Следующий уровень",
        "more_needed": "ещё {amount}",
        "deposit_vs_spend": "Пополнения и траты",
        "max_level": "Максимальный уровень достигнут!",
        "dashboard_balance": "Баланс",
        "dashboard_level": "VIP",
        "support": "Поддержка",
        "owner": "Владелец",
        "currency_set": "Валюта изменена на {name}.",
        "language_set": "Язык изменён на {name}.",
        "unsupported_currency": "Эта валюта не поддерживается.",
        "unsupported_language": "Этот язык не поддерживается.",
        "level_bronze": "Бронза",
        "level_silver": "Серебро",
        "level_gold": "Золото",
        "level_platinum": "Платина",
        "level_diamond": "Алмаз",
    },
    "zh": {
        "settings_title": "设置",
        "settings_note": "选择价格和语言的显示方式。",
        "currency": "货币",
        "language": "语言",
        "prices_note": "INR 同时显示 ₹ 和 USDT。USDT 仅显示 USDT。",
        "back": "返回",
        "profile_title": "用户资料",
        "user_id": "用户 ID",
        "balance": "余额",
        "deposited": "已充值",
        "referred_users": "已推荐用户",
        "joined": "加入时间",
        "referral_link": "您的推荐链接",
        "share_note": "分享此链接给朋友即可赚取奖励！",
        "stats_title": "我的统计",
        "accounts_bought": "已购账号",
        "referrals": "推荐",
        "total_spent": "总支出",
        "total_deposited": "总充值",
        "view_purchases": "查看购买记录",
        "referral_logs": "推荐记录",
        "level": "等级",
        "next_tier": "下一等级",
        "more_needed": "还需 {amount}",
        "deposit_vs_spend": "充值对比支出",
        "max_level": "已达到最高等级！",
        "dashboard_balance": "余额",
        "dashboard_level": "VIP",
        "support": "支持",
        "owner": "所有者",
        "currency_set": "货币已更改为 {name}。",
        "language_set": "语言已更改为 {name}。",
        "unsupported_currency": "不支持该货币。",
        "unsupported_language": "不支持该语言。",
        "level_bronze": "青铜",
        "level_silver": "白银",
        "level_gold": "黄金",
        "level_platinum": "铂金",
        "level_diamond": "钻石",
    },
    "ar": {
        "settings_title": "الإعدادات",
        "settings_note": "اختر طريقة عرض الأسعار واللغة.",
        "currency": "العملة",
        "language": "اللغة",
        "prices_note": "INR يعرض ₹ و USDT معًا. USDT يعرض USDT فقط.",
        "back": "رجوع",
        "profile_title": "الملف الشخصي",
        "user_id": "معرّف المستخدم",
        "balance": "الرصيد",
        "deposited": "الإيداع",
        "referred_users": "المستخدمون المُحالون",
        "joined": "تاريخ الانضمام",
        "referral_link": "رابط الإحالة الخاص بك",
        "share_note": "شارك هذا الرابط مع أصدقائك لكسب المكافآت!",
        "stats_title": "إحصائياتي",
        "accounts_bought": "الحسابات المشتراة",
        "referrals": "الإحالات",
        "total_spent": "إجمالي المصروف",
        "total_deposited": "إجمالي الإيداع",
        "view_purchases": "عرض سجل المشتريات",
        "referral_logs": "سجل الإحالات",
        "level": "المستوى",
        "next_tier": "المستوى التالي",
        "more_needed": "المزيد {amount}",
        "deposit_vs_spend": "الإيداع مقابل المصروف",
        "max_level": "تم الوصول إلى أعلى مستوى!",
        "dashboard_balance": "الرصيد",
        "dashboard_level": "VIP",
        "support": "الدعم",
        "owner": "المالك",
        "currency_set": "تم تغيير العملة إلى {name}.",
        "language_set": "تم تغيير اللغة إلى {name}.",
        "unsupported_currency": "هذه العملة غير مدعومة.",
        "unsupported_language": "هذه اللغة غير مدعومة.",
        "level_bronze": "برونزي",
        "level_silver": "فضي",
        "level_gold": "ذهبي",
        "level_platinum": "بلاتيني",
        "level_diamond": "ألماس",
    },
}


def get_lang(uid=None):
    """Return the user's language code, defaulting to English."""
    if uid is None:
        return DEFAULT_LANG
    try:
        from database import get_user_language
        code = str(get_user_language(uid) or DEFAULT_LANG).lower()
    except Exception:
        code = DEFAULT_LANG
    return code if code in TRANSLATIONS else DEFAULT_LANG


def t(uid, key, default=None, **kwargs):
    """Translate ``key`` for ``uid``.

    Falls back to English, then to ``default`` (or the raw key).  Any
    ``str.format`` placeholders are filled from ``kwargs`` and a formatting
    error never propagates to the caller.
    """
    lang = get_lang(uid)
    table = TRANSLATIONS.get(lang, TRANSLATIONS[DEFAULT_LANG])
    text = table.get(key)
    if text is None:
        text = TRANSLATIONS[DEFAULT_LANG].get(key)
    if text is None:
        text = default if default is not None else key
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text
