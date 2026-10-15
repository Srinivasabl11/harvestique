"""Rule-based recognition of a LIMITED set of farmer/buyer intents in English and Kannada.

Deterministic and testable. Unrecognised input returns UNKNOWN rather than a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import StrEnum

from app.core.enums import ExpenseCategory, ReminderType

KANNADA = re.compile(r"[ಀ-೿]")


class Intent(StrEnum):
    WEATHER = "weather"
    HARVEST_PREDICTION = "harvest_prediction"
    FARM_RISK = "farm_risk"
    REMINDERS_LIST = "reminders_list"
    REMINDER_CREATE = "reminder_create"
    INVENTORY = "inventory"
    BUYER_OPPORTUNITIES = "buyer_opportunities"
    SUPPLY_REQUESTS = "supply_requests"
    MY_ORDERS = "my_orders"
    MARKET_SUPPLY = "market_supply"
    INCOME_PLANS = "income_plans"
    EXPENSE_SUMMARY = "expense_summary"
    FARM_SUMMARY = "farm_summary"
    EXPENSE_RECORD = "expense_record"  # proposes a write; it runs only after the farmer confirms
    CROP_HEALTH_HELP = "crop_health_help"
    ALLOCATION_REQUEST = "allocation_request"  # always refused: allocation is decided by the pool engine
    CROP_ESTIMATE = "crop_estimate"  # cost / revenue / profit of a crop on N acres (deterministic calculator)
    CROP_RECOMMENDATION = "crop_recommendation"  # "what crops are best for my farm?": records + season shortlist
    CROP_STATEMENT = "crop_statement"  # "I am growing mango": context, checked against the farm records
    CROP_SUITABILITY = "crop_suitability"  # "can I grow carrots on my farm?": farm facts + labelled advice
    NAVIGATE = "navigate"  # open an app screen from an allowlist (slots["target"]); never model-generated
    HELP = "help"
    GENERAL = "general"  # a general-knowledge question (answered by the local model, never from records)
    UNKNOWN = "unknown"


# Kannada patterns use word STEMS without \b: Kannada is inflected ("ಜಮೀನುಗಳಿವೆ", "ಬೆಳೆಗಳನ್ನು") and Python's \b falls
# inside Kannada words (vowel signs are not "word" characters). Android's kn-IN recogniser writes English words
# spoken in Kannada in Kannada script ("ಫಾರ್ಮ್", "ವೆದರ್"), so those loanwords are listed too.
_FARM = r"(farms?|fields?|plots?|ಜಮೀನ|ಹೊಲ|ಫಾರ್ಮ್|ತೋಟ|ಗದ್ದೆ)"
_CROP = r"(crops?|ಬೆಳೆ|ಕ್ರಾಪ್)"
_HARVEST = r"(harvest|yield|ಇಳುವರಿ|ಕೊಯ್ಲು|ಹಾರ್ವೆಸ್ಟ್|ಯೀಲ್ಡ್)"
_DEMAND = r"(demand|buyers?|ಬೇಡಿಕೆ|ಖರೀದಿದಾರ|ಡಿಮ್ಯಾಂಡ್|ಬೈಯರ್|ಬಯರ್)"
_PROFIT = r"(profit|income|ಲಾಭ|ಆದಾಯ|ಪ್ರಾಫಿಟ್|ಇನ್ಕಮ್)"
_ESTIMATE = r"(estimate|possible|could|would|will i|expected|acres?\b|ಅಂದಾಜು|ಎಕರೆ|ಆಗಬಹುದು|ಬರಬಹುದು|ಬರುತ್ತ|ಸಿಗುತ್ತ)"

# order matters: the first matching rule wins (more specific rules first)
RULES: tuple[tuple[Intent, tuple[str, ...]], ...] = (
    (
        Intent.ALLOCATION_REQUEST,
        (
            r"\b(allocate|re-?allocate|assign|reserve|book|move|transfer|commit)\b.*\b\d+\s*(kg|kgs|kilo)",
            r"\b(allocate|allocation|re-?allocate)\b",
            r"ಹಂಚಿಕೆ",
            r"ಮೀಸಲು",
        ),
    ),
    (
        Intent.REMINDER_CREATE,
        (r"\bremind me\b", r"\b(set|add|create|make)\b.*\breminder\b", r"ನೆನಪಿಸು", r"ಜ್ಞಾಪನೆ\s*(ಸೇರಿಸು|ಹಾಕು|ಮಾಡು)"),
    ),
    (
        # "what crops are best to grow on my farm?" names no crop: a shortlist, not one crop's suitability
        Intent.CROP_RECOMMENDATION,
        (
            r"\b(what|which) (crops?|plants?|vegetables?) (are|is|would be|will be)( the)? (best|good|suitable|right|ideal)",
            r"\b(what|which) (crops?|plants?|vegetables?) (should|can|could|do|to) (i|we )?\s*(grow|plant|sow|cultivate)",
            r"\bwhat (should|can|could) (i|we) (grow|plant|sow|cultivate)\b",
            r"\bbest crops?\b",
            r"\b(recommend|suggest)\w* (me )?(some |a |which |good )?crops?\b",
            r"ಯಾವ\s+ಬೆಳೆ\S*(\s+\S+){0,4}\s*(ಉತ್ತಮ|ಒಳ್ಳೆಯ|ಸೂಕ್ತ|ಬೆಳೆಯಬೇಕು|ಬೆಳೆಯಲಿ|ಹಾಕಲಿ|ಹಾಕಬೇಕು|ಬೆಳೆಯಬಹುದು|ಬೆಳೆಸಬಹುದು)",
            r"ಏನು\s+ಬೆಳೆ(ಯ|ಸ)(ಬೇಕು|ಲಿ|ಬಹುದು)",
        ),
    ),
    (
        Intent.CROP_SUITABILITY,
        (
            r"\b(can|could|should) (i|we) (grow|plant|cultivate|sow)\b",
            r"\bsuitable (for|to grow)\b|\b(is|are) [a-z ]+ suitable\b",
            r"\bwill [a-z ]+ grow (well )?(here|on my|in my)\b",
            r"ಬೆಳೆಯ(ಬಹುದ|ಬಲ್ಲೆ|ಬಹುದಾ)",
            r"ಬೆಳೆಸ(ಬಹುದ|ಬಹುದಾ)",
            r"ಸೂಕ್ತವಾ|ಸೂಕ್ತವೇ|ಸೂಕ್ತನಾ|ಹೊಂದುತ್ತ",
        ),
    ),
    (
        # "cost and possible profit of cucumber on one acre": the calculator, not past expenses or saved plans
        Intent.CROP_ESTIMATE,
        (
            rf"{_PROFIT}.*{_ESTIMATE}|{_ESTIMATE}.*{_PROFIT}",
            r"(cost|ಖರ್ಚ|ವೆಚ್ಚ).*(acre|ಎಕರೆ)|(acre|ಎಕರೆ).*(cost|ಖರ್ಚ|ವೆಚ್ಚ)",
            # "one acre of tomato, price 20 rupees per kg"
            r"(per kg|/kg|ಕೆಜಿಗೆ|per quintal|ಕ್ವಿಂಟಾಲ್ಗೆ).*(acre|ಎಕರೆ)|(acre|ಎಕರೆ).*(per kg|/kg|ಕೆಜಿಗೆ|per quintal|ಕ್ವಿಂಟಾಲ್ಗೆ)",
        ),
    ),
    (
        Intent.EXPENSE_SUMMARY,
        (r"\b(spent|spend|spending|expenses?|expenditure)\b", r"ಖರ್ಚ", r"ವೆಚ್ಚ", r"ಎಕ್ಸ್ಪೆನ್ಸ್", r"ಹಣ\S*\s+ಹೋಯ"),
    ),
    (
        Intent.REMINDERS_LIST,
        (r"\breminders?\b", r"\btasks?\b", r"\bto ?do\b", r"ಜ್ಞಾಪನೆ", r"ಕೆಲಸ", r"ರಿಮೈಂಡರ್", r"ಟಾಸ್ಕ್"),
    ),
    (
        Intent.CROP_HEALTH_HELP,
        (
            r"\b(disease|pest|insect|fungus|leaf|leaves|yellow|wilt|spots?|sick|crop health)\b",
            r"ರೋಗ",
            r"ಕೀಟ",
            r"ಎಲೆ",
            r"ಹಳದಿ",
            r"ಡಿಸೀಸ್",
        ),
    ),
    (
        Intent.WEATHER,
        (
            r"\b(weather|rain|rainfall|temperature|forecast|hot|heat)\b",
            r"ಹವಾಮಾನ",
            r"ಮಳೆ",
            r"ತಾಪಮಾನ",
            r"ಬಿಸಿ",
            r"ವೆದರ್",
            r"ಟೆಂಪರೇಚರ್",
            r"ಫೋರ್ಕಾಸ್ಟ್",
        ),
    ),
    (Intent.FARM_RISK, (r"\brisks?\b", r"\bdanger\b", r"ಅಪಾಯ", r"ರಿಸ್ಕ್")),
    # "check my predicted harvest against buyer demand": the comparison, not the harvest forecast alone
    (Intent.BUYER_OPPORTUNITIES, (rf"{_HARVEST}.*{_DEMAND}|{_DEMAND}.*{_HARVEST}",)),
    (
        Intent.HARVEST_PREDICTION,
        (r"\b(harvest|yield|prediction|predict|how much will)\b", r"ಕೊಯ್ಲು", r"ಇಳುವರಿ", r"ಅಂದಾಜು", r"ಹಾರ್ವೆಸ್ಟ್", r"ಯೀಲ್ಡ್"),
    ),
    (
        Intent.SUPPLY_REQUESTS,
        (r"\b(supply )?requests?\b", r"\baccept\b", r"\bparticipat", r"ವಿನಂತಿ", r"ರಿಕ್ವೆಸ್ಟ್"),
    ),
    (Intent.MY_ORDERS, (r"\b(my )?orders?\b", r"\bdeliver(y|ies)\b", r"\bpools?\b", r"ಆರ್ಡರ್")),
    (Intent.INVENTORY, (r"\b(inventory|stock|available|lots?)\b", r"ದಾಸ್ತಾನು", r"ಸಂಗ್ರಹ", r"ಸ್ಟಾಕ್", r"ಲಭ್ಯ")),
    (Intent.MARKET_SUPPLY, (r"\b(supply|farmers? (have|selling))\b",)),
    (
        Intent.BUYER_OPPORTUNITIES,
        (
            r"\b(buyers?|demand|sell|selling|market)\b",
            r"ಖರೀದಿದಾರ",
            r"ಮಾರಾಟ",
            r"ಮಾರುಕಟ್ಟೆ",
            r"ಬೇಡಿಕೆ",
            r"ಮಾರ್ಕೆಟ್",
            r"ಡಿಮ್ಯಾಂಡ್",
            r"ಬೈಯರ್",
        ),
    ),
    (
        Intent.INCOME_PLANS,
        (r"\b(income|profit|plan|plans|margin)\b", r"ಆದಾಯ", r"ಲಾಭ", r"ಯೋಜನೆ", r"ಪ್ರಾಫಿಟ್", r"ಇನ್ಕಮ್", r"ಪ್ಲಾನ್"),
    ),
    (
        Intent.FARM_SUMMARY,
        (
            r"\bhow many (farms?|plots?|fields?|crops?|acres)\b",
            r"\b(list|show|tell me about|what are) (me )?(all )?my (farms?|plots?|fields?|crops?)\b",
            r"\bwhat (crops )?am i growing\b",
            rf"ಎಷ್ಟು\s*({_FARM}|{_CROP})",
            rf"({_FARM}|{_CROP})\S*\s+ಎಷ್ಟು",
            rf"ನನ್ನ\s+({_FARM}|{_CROP})\S*(\s+\S+){{0,3}}\s*(ತೋರಿಸ|ಹೇಳ|ಯಾವುವು|ಯಾವುದು|ಪಟ್ಟಿ|ವಿವರ)",
            r"ಯಾವ\s+ಬೆಳೆ\S*\s+ಬೆಳೆಯ",
        ),
    ),
    (Intent.HELP, (r"\bhelp\b", r"what can you do", r"ಸಹಾಯ", r"(ನೀನು|ನೀವು)\s+ಏನು\s+ಮಾಡ")),
)

# "I am growing mango on my farm" / "ನಾನು ನನ್ನ ಜಮೀನಿನಲ್ಲಿ ಮಾವು ಬೆಳೆಯುತ್ತಿದ್ದೇನೆ": a statement about the farm, not a question.
# It used to fall through to "sorry, I did not understand" (Kannada) or a generic model answer (English).
STATEMENT = re.compile(
    r"\b(i am|i'm|im|i m|we are|we're|we re) (growing|cultivating|planting|farming)\b"
    r"|\b(i|we) (grow|cultivate|have planted|planted|sowed|have sown|sow)\b"
    r"|ಬೆಳೆಯುತ್ತಿದ್ದೇ(ನೆ|ವೆ)|ಬೆಳೆಸುತ್ತಿದ್ದೇ(ನೆ|ವೆ)|ಬೆಳೆದಿದ್ದೇ(ನೆ|ವೆ)|ಬೆಳೆಯುತ್ತೇ(ನೆ|ವೆ)|ಬೆಳೆಸುತ್ತೇ(ನೆ|ವೆ)"
    r"|ನೆಟ್ಟಿದ್ದೇ(ನೆ|ವೆ)|ಬಿತ್ತಿದ್ದೇ(ನೆ|ವೆ)|ಹಾಕಿದ್ದೇ(ನೆ|ವೆ)"
)
QUESTION_FORM = re.compile(r"\b(what|which|how|when|why|where|can|should)\b|ಯಾವ|ಏನು|ಎಷ್ಟು|ಹೇಗೆ|ಯಾವಾಗ|ಯಾಕೆ|ಏಕೆ")

# --------------------------------------------------------------- navigation
# Spoken "open Market" / "ಮಾರುಕಟ್ಟೆ ತೆರೆಯಿರಿ" maps ONLY to these screen keys; the app decides which exist for the role.
NAV_TARGETS = (
    "back",
    "home",
    "my_farm",
    "market",
    "harvest",
    "reminders",
    "crop_health",
    "planning",
    "notifications",
    "orders",
    "demands",
)
_NAV_VERB = re.compile(
    r"\b(open|go to|take me to|navigate to|switch to|show (the )?(screen|page|tab))\b|^(go|take me) (back|home)\b"
    r"|ತೆರೆ|ಓಪನ್|ಹೋಗು|ಹೋಗಿ(?!ದ)|ಕರೆದುಕೊಂಡು|ಕರ್ಕೊಂಡು"
)
_NAV_TARGET: tuple[tuple[str, str], ...] = (
    ("back", r"\bback\b|ಹಿಂದೆ|ಹಿಂದಕ್ಕೆ"),
    ("crop_health", r"crop health|plant health|photo check|ಬೆಳೆ\s*ಆರೋಗ್ಯ|ಕ್ರಾಪ್\s*ಹೆಲ್ತ್|ಆರೋಗ್ಯ\s*ಪರೀಕ್ಷ"),
    ("planning", r"planning|\bplans?\b|planner|ಯೋಜನೆ|ಪ್ಲಾನ್"),
    ("notifications", r"notifications?|alerts?|ಸೂಚನೆ|ನೋಟಿಫಿಕೇಶನ್"),
    ("reminders", r"reminders?|calendar|ಜ್ಞಾಪನೆ|ರಿಮೈಂಡರ್|ಕ್ಯಾಲೆಂಡರ್"),
    ("harvest", r"harvest|ಕೊಯ್ಲು|ಹಾರ್ವೆಸ್ಟ್"),
    ("orders", r"orders?|ಆರ್ಡರ್"),
    ("demands", r"demands?|ಬೇಡಿಕೆ|ಡಿಮ್ಯಾಂಡ್"),
    ("market", r"market|ಮಾರುಕಟ್ಟೆ|ಮಾರ್ಕೆಟ್"),
    ("my_farm", _FARM),
    ("home", r"\bhome\b|ಮುಖಪುಟ|ಹೋಮ್"),
)


def navigation_target(norm: str) -> str | None:
    """'open market' -> 'market'. Needs an explicit open/go verb and a short command; reminders win ('remind me to
    go to the field' is a reminder, not navigation)."""
    if len(norm.split()) > 7 or not _NAV_VERB.search(norm) or re.search(r"\bremind\b|ನೆನಪಿಸು", norm):
        return None
    return next((key for key, pat in _NAV_TARGET if re.search(pat, norm)), None)


_INVISIBLE = re.compile("[\u200b-\u200d\ufeff]")
_PUNCT = re.compile(r"[?!.,;:।॥\"'“”‘’()\[\]]")


def normalise(text: str) -> str:
    """Lower case, Kannada digits as 0-9, zero-width joiners and punctuation removed, spaces collapsed. The kn-IN
    recogniser inserts zero-width non-joiners ("ಆರ್ಡರ್‌ಗಳು") that would otherwise break the stems."""
    text = _INVISIBLE.sub("", text.lower().translate(KANNADA_DIGITS))
    return " ".join(_PUNCT.sub(" ", text).split())


@dataclass(frozen=True, slots=True)
class Recognised:
    intent: Intent
    confidence: float  # rule-match strength, not a probability of correctness
    language: str
    matched: str | None = None
    slots: dict[str, object] = field(default_factory=dict)


def detect_language(text: str, preferred: str | None = None) -> str:
    if KANNADA.search(text):
        return "kn"
    return preferred if preferred in ("en", "kn") else "en"


def recognise(text: str, preferred_language: str | None = None, *, today: date | None = None) -> Recognised:
    lang = detect_language(text, preferred_language)
    norm = normalise(text)
    if not norm:
        return Recognised(Intent.UNKNOWN, 0.0, lang)
    if (target := navigation_target(norm)) is not None:
        return Recognised(Intent.NAVIGATE, 0.9, lang, "navigate", {"target": target})
    if (record := expense_record_slots(text, today or date.today())) is not None:
        return Recognised(Intent.EXPENSE_RECORD, 0.9, lang, "expense_record", record)
    hits = [(intent, pat) for intent, pats in RULES for pat in pats if re.search(pat, norm)]
    if not hits:
        if STATEMENT.search(norm) and not QUESTION_FORM.search(norm):
            return Recognised(Intent.CROP_STATEMENT, 0.8, lang, "statement")
        return Recognised(Intent.UNKNOWN, 0.0, lang)
    intent, pat = hits[0]
    others = {i for i, _ in hits[1:] if i is not intent}
    confidence = 0.9 if not others else 0.6  # several intents matched: lower confidence, first rule wins
    slots: dict[str, object] = {}
    if intent is Intent.REMINDER_CREATE:
        slots = reminder_slots(text, today or date.today())
    elif intent is Intent.EXPENSE_SUMMARY:
        slots = expense_summary_slots(text, today or date.today())
    return Recognised(intent, confidence, lang, pat, slots)


# ------------------------------------------------------------------ follow-ups
FOLLOW_UP = re.compile(r"^(and|also|what about|how about|same for|ok,? and|then|for)\b|^(ಮತ್ತೆ|ಮತ್ತು|ಹಾಗಾದರೆ|ಅದೇ|ಹಾಗೆಯೇ)")


def is_follow_up(text: str) -> bool:
    """'what about ragi?', 'and tomorrow?', 'ಮತ್ತೆ ನಾಳೆ?': a question that only makes sense after the previous one."""
    norm = " ".join(text.lower().split())
    return bool(FOLLOW_UP.search(norm)) or (0 < len(norm.split()) <= 3 and norm.endswith("?"))


# --------------------------------------------------------------------- expenses
_CATEGORY_WORDS: tuple[tuple[ExpenseCategory, tuple[str, ...]], ...] = (
    (ExpenseCategory.PESTICIDE, ("pesticide", "insecticide", "fungicide", "spray", "ಕೀಟನಾಶಕ", "ಔಷಧ", "ಸಿಂಪಡಣೆ")),
    (ExpenseCategory.FERTILIZER, ("fertili", "urea", "dap", "manure", "compost", "ಗೊಬ್ಬರ", "ಯೂರಿಯಾ")),
    (ExpenseCategory.SEED, ("seed", "sapling", "seedling", "ಬೀಜ", "ಸಸಿ")),
    (ExpenseCategory.LABOUR, ("labour", "labor", "worker", "wage", "coolie", "ಕೂಲಿ", "ಕಾರ್ಮಿಕ", "ಆಳು")),
    (ExpenseCategory.IRRIGATION, ("irrigat", "water", "pump", "borewell", "drip", "ನೀರಾವರಿ", "ನೀರು", "ಪಂಪ್")),
    (ExpenseCategory.MACHINERY, ("tractor", "machine", "tiller", "harvester", "ಟ್ರ್ಯಾಕ್ಟರ್", "ಯಂತ್ರ")),
    (ExpenseCategory.TRANSPORT, ("transport", "lorry", "truck", "tempo", "auto", "ಸಾಗಣೆ", "ಲಾರಿ", "ಸಾರಿಗೆ")),
)
_RECORD = re.compile(
    r"\b(i\s+)?(spent|paid|bought|purchased)\b|\b(record|add|note|log)\b.*\bexpense\b"
    r"|ಖರ್ಚು\s*ಮಾಡಿದೆ|ಖರ್ಚಾಯಿತು|ಖರ್ಚು\s*ಆಯಿತು|ಕೊಟ್ಟೆ|ಖರೀದಿಸಿದೆ|ಖರ್ಚು\s*(ಸೇರಿಸು|ದಾಖಲಿಸು|ಬರೆ)"
)
_QUESTION = re.compile(r"\bhow much\b|\bwhat\b|\btotal\b|\?|ಎಷ್ಟು|ಏನು|ಒಟ್ಟು")
_AMOUNT = re.compile(r"(?<![\d-])(\d{1,3}(?:,\d{2,3})+|\d+)(\.\d{1,2})?(?![\d-])")
KANNADA_DIGITS = str.maketrans("೦೧೨೩೪೫೬೭೮೯", "0123456789")


def expense_category(text: str) -> ExpenseCategory | None:
    low = text.lower()
    return next((c for c, words in _CATEGORY_WORDS if any(w in low for w in words)), None)


def expense_record_slots(text: str, today: date) -> dict[str, object] | None:
    """'I spent 1,500 rupees on urea yesterday' -> amount, category, date. None when this is not a recording.

    Questions ('how much did I spend?') are never recordings. A missing amount or category is left empty so the
    assistant asks instead of guessing."""
    low = " ".join(text.lower().translate(KANNADA_DIGITS).split())
    if not _RECORD.search(low) or _QUESTION.search(low):
        return None
    cleaned = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", low)
    m = _AMOUNT.search(cleaned)
    amount = f"{m.group(1).replace(',', '')}{m.group(2) or ''}" if m else None
    when = today
    if re.search(r"\bday before yesterday\b|ಮೊನ್ನೆ", low):
        when = today - timedelta(days=2)
    elif re.search(r"\byesterday\b|ನಿನ್ನೆ", low):
        when = today - timedelta(days=1)
    return {"amount": amount, "category": expense_category(low), "date": when, "description": text.strip()[:255]}


def expense_summary_slots(text: str, today: date) -> dict[str, object]:
    """Period and category of an expense question. No period word = everything recorded."""
    low = text.lower()
    category = expense_category(low)
    if re.search(r"\blast month\b|ಕಳೆದ ತಿಂಗಳ", low):
        first = today.replace(day=1)
        return {
            "from": (first - timedelta(days=1)).replace(day=1),
            "to": first - timedelta(days=1),
            "period": "last_month",
            "category": category,
        }
    start: date | None = None
    period = "all"
    if re.search(r"\bthis month\b|ಈ ತಿಂಗಳ", low):
        start, period = today.replace(day=1), "this_month"
    elif re.search(r"\bthis week\b|ಈ ವಾರ", low):
        start, period = today - timedelta(days=6), "this_week"
    elif re.search(r"\bthis year\b|ಈ ವರ್ಷ", low):
        start, period = today.replace(month=1, day=1), "this_year"
    elif m := re.search(r"\b(?:last|past) (\d{1,3}) days\b|(\d{1,3})\s*ದಿನ", low):
        start, period = today - timedelta(days=int(m.group(1) or m.group(2)) - 1), "days"
    return {"from": start, "to": today if start else None, "period": period, "category": category}


_TYPE_WORDS: tuple[tuple[ReminderType, tuple[str, ...]], ...] = (
    (ReminderType.IRRIGATION, ("irrigat", "water", "ನೀರು")),
    (ReminderType.HARVEST, ("harvest", "ಕೊಯ್ಲು")),
    (ReminderType.CROP_OBSERVATION, ("observ", "check the crop", "inspect", "ಪರಿಶೀಲಿಸ")),
    (ReminderType.CROP_HEALTH, ("spray", "pest", "disease", "ಕೀಟ", "ರೋಗ", "ಔಷಧ")),
    (ReminderType.EXPENSE, ("expense", "pay", "bill", "ಖರ್ಚು")),
    (ReminderType.COLLECTION, ("collection", "hub", "deliver", "ಸಂಗ್ರಹ ಕೇಂದ್ರ")),
    (ReminderType.ACTIVITY, ("fertili", "weed", "sow", "prune", "ಗೊಬ್ಬರ", "ಕಳೆ", "ಬಿತ್ತನೆ")),
)


def reminder_slots(text: str, today: date) -> dict[str, object]:
    """Extract what we can (date, hour, type, title). Missing date -> None: the user is asked, never guessed."""
    low = text.lower()
    when: date | None = None
    if re.search(r"\btoday\b|ಇಂದು", low):
        when = today
    elif re.search(r"\bday after tomorrow\b|ನಾಡಿದ್ದು", low):
        when = today + timedelta(days=2)
    elif re.search(r"\btomorrow\b|ನಾಳೆ", low):
        when = today + timedelta(days=1)
    elif m := re.search(r"\bin (\d{1,2}) days?\b|(\d{1,2})\s*ದಿನ", low):
        when = today + timedelta(days=int(m.group(1) or m.group(2)))
    elif m := re.search(r"\b(\d{4}-\d{2}-\d{2})\b", low):
        try:
            when = date.fromisoformat(m.group(1))
        except ValueError:
            when = None
    hour = 9
    if m := re.search(r"\b(?:at\s*)?(\d{1,2})\s*(am|pm)\b", low):
        hour = int(m.group(1)) % 12 + (12 if m.group(2) == "pm" else 0)
    elif m := re.search(r"\bat\s*(\d{1,2})(?::00)?\b", low):
        hour = int(m.group(1)) if int(m.group(1)) < 24 else 9
    kind = next((k for k, words in _TYPE_WORDS if any(w in low for w in words)), ReminderType.CUSTOM)
    title = re.sub(
        r"\b(please|remind me( to)?|set (a )?reminder( to)?|add (a )?reminder( to)?)\b", "", text, flags=re.I
    )
    title = re.sub(
        r"\b(today|tomorrow|day after tomorrow|in \d{1,2} days?|at \d{1,2}(:00)?\s*(am|pm)?|\d{1,2}\s*(am|pm)|\d{4}-\d{2}-\d{2})\b",
        "",
        title,
        flags=re.I,
    )
    title = re.sub(r"(ನೆನಪಿಸು|ಜ್ಞಾಪನೆ\s*(ಸೇರಿಸು|ಹಾಕು|ಮಾಡು)|ಇಂದು|ನಾಳೆ|ನಾಡಿದ್ದು)", "", title)
    title = " ".join(title.split()).strip(" ,.-") or ("Reminder" if not KANNADA.search(text) else "ಜ್ಞಾಪನೆ")
    return {"date": when, "hour": min(max(hour, 0), 23), "reminder_type": kind, "title": title[:160]}


def local_due(when: date, hour: int) -> datetime:
    """The reminder time in India Standard Time (UTC+05:30), as an aware datetime."""
    from datetime import timezone

    return datetime.combine(when, time(hour, 0), tzinfo=timezone(timedelta(hours=5, minutes=30)))


# --------------------------------------------------------------- question scope
PERSONAL = re.compile(r"\b(my|mine|our|ours|i|i'm|i've|i'd|me)\b|ನನ್ನ|ನನಗೆ|ನಾನು|ನಮ್ಮ|ನಮಗೆ|ನನ್ನದು")
GENERAL_FORM = re.compile(
    r"\b(how (to|do|does|can|should|is)|why|explain|what causes|what (is|are) (a|an)|meaning of|tips?|"
    r"best (way|time|practice|method|season)|ways to|difference between|advice|recommend)\b"
    r"|ಹೇಗೆ|ಏಕೆ|ಯಾಕೆ|ಸಲಹೆ|ಅಂದರೆ ಏನು|ಎಂದರೇನು"
)


def question_scope(text: str) -> str:
    """'personal' (about the asker's own records), 'general' (knowledge, advice) or 'mixed' (both).

    'how much did I spend' -> personal; 'what is a rain shadow' -> general;
    'how can I reduce my fertilizer costs' -> mixed. Plain 'what is the weather' stays personal (their farm)."""
    low = " ".join(text.lower().split())
    personal = bool(PERSONAL.search(low))
    general = bool(GENERAL_FORM.search(low))
    if personal and general:
        return "mixed"
    if general:
        return "general"
    return "personal"
