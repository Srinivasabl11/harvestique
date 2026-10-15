"""Privacy-safe evaluation corpus for the voice assistant's understanding step (transcript -> intent).

Written by the developers, not recorded from farmers. Each transcript is phrased the way Android's speech recogniser
writes Kannada (kn-IN): inflected words ("ಬೆಳೆಗಳನ್ನು"), English loanwords in Kannada script ("ಫಾರ್ಮ್", "ವೆದರ್"),
mixed scripts ("ನನ್ನ farm"), Kannada digits and zero-width joiners. Speech-to-text itself runs on the phone and is
not measured here; this corpus measures what the server does with the text it receives.

expected: the acceptable intents ("navigate:<target>" for app navigation). "unknown" means no record tool may be
used (the server must ask or answer generally, never guess a tool).
"""

from __future__ import annotations

from typing import NamedTuple


class Case(NamedTuple):
    text: str
    expected: frozenset[str]
    lang: str
    note: str = ""


def c(text: str, *expected: str, note: str = "") -> Case:
    lang = "kn" if any("ಀ" <= ch <= "೿" for ch in text) else "en"
    return Case(text, frozenset(expected), lang, note)


CORPUS: tuple[Case, ...] = (
    # --- the 14 required tasks, English
    c("How many farms do I have?", "farm_summary"),
    c("What will the weather be like tomorrow in my field?", "weather"),
    c("Can I grow cucumber here?", "crop_suitability"),
    c("Estimate the cost and possible profit for one acre", "crop_estimate"),
    c("Check my predicted harvest against buyer demand", "buyer_opportunities"),
    c("What reminders are due today?", "reminders_list"),
    c("Open My Farm", "navigate:my_farm"),
    c("Show my crops", "farm_summary"),
    c("Open crop health", "navigate:crop_health"),
    c("Take me to income planning", "navigate:planning"),
    c("Open Harvest", "navigate:harvest"),
    c("Show buyer requests", "supply_requests"),
    c("Open Market", "navigate:market"),
    c("Go back", "navigate:back"),
    # --- the same tasks, Kannada as the recogniser writes it
    c("ನನ್ನ ಬಳಿ ಎಷ್ಟು ಜಮೀನುಗಳಿವೆ", "farm_summary"),
    c("ನನಗೆ ಎಷ್ಟು ಫಾರ್ಮ್ ಇದೆ", "farm_summary", note="loanword"),
    c("ನನ್ನ ಜಮೀನು ಎಷ್ಟು ಇದೆ", "farm_summary", note="word order"),
    c("ನಾಳೆ ನನ್ನ ಹೊಲದಲ್ಲಿ ಹವಾಮಾನ ಹೇಗಿರುತ್ತದೆ", "weather"),
    c("ನಾಳೆ ವೆದರ್ ಹೇಗಿದೆ", "weather", note="loanword"),
    c("ನಾಳೆ ಮಳೆ ಬರುತ್ತಾ", "weather"),
    c("ನಾನು ಇಲ್ಲಿ ಸೌತೆಕಾಯಿ ಬೆಳೆಯಬಹುದೇ", "crop_suitability", note="farm facts + labelled advice"),
    c("ಒಂದು ಎಕರೆಗೆ ಖರ್ಚು ಮತ್ತು ಲಾಭ ಎಷ್ಟು ಆಗಬಹುದು ಅಂದಾಜು ಮಾಡಿ", "crop_estimate", note="not past expenses"),
    c("ಒಂದು ಎಕರೆಗೆ ಎಷ್ಟು ಲಾಭ ಬರುತ್ತೆ", "crop_estimate"),
    c("ನನ್ನ ಅಂದಾಜು ಇಳುವರಿಯನ್ನು ಖರೀದಿದಾರರ ಬೇಡಿಕೆಯೊಂದಿಗೆ ಹೋಲಿಸಿ", "buyer_opportunities"),
    c("ಇವತ್ತು ಯಾವ ಜ್ಞಾಪನೆಗಳಿವೆ", "reminders_list"),
    c("ಇವತ್ತಿನ ರಿಮೈಂಡರ್ ಏನು", "reminders_list", note="loanword"),
    c("ಇಂದು ಮಾಡಬೇಕಾದ ಕೆಲಸಗಳು ಯಾವುವು", "reminders_list"),
    c("ನನ್ನ ಫಾರ್ಮ್ ತೆರೆಯಿರಿ", "navigate:my_farm"),
    c("ನನ್ನ ಜಮೀನು ತೆರೆಯಿರಿ", "navigate:my_farm"),
    c("ನನ್ನ ಬೆಳೆಗಳನ್ನು ತೋರಿಸು", "farm_summary", note="accusative"),
    c("ನಾನು ಯಾವ ಬೆಳೆ ಬೆಳೆಯುತ್ತಿದ್ದೇನೆ", "farm_summary"),
    c("ಬೆಳೆ ಆರೋಗ್ಯ ತೆರೆಯಿರಿ", "navigate:crop_health"),
    c("ಆದಾಯ ಯೋಜನೆಗೆ ಕರೆದುಕೊಂಡು ಹೋಗಿ", "navigate:planning"),
    c("ಕೊಯ್ಲು ತೆರೆಯಿರಿ", "navigate:harvest"),
    c("ಹಾರ್ವೆಸ್ಟ್ ಓಪನ್ ಮಾಡಿ", "navigate:harvest", note="loanwords"),
    c("ಖರೀದಿದಾರರ ವಿನಂತಿಗಳನ್ನು ತೋರಿಸು", "supply_requests"),
    c("ಮಾರುಕಟ್ಟೆ ತೆರೆಯಿರಿ", "navigate:market"),
    c("ಮಾರ್ಕೆಟ್ ಓಪನ್ ಮಾಡು", "navigate:market", note="loanwords"),
    c("ಹಿಂದೆ ಹೋಗು", "navigate:back"),
    # --- mixed Kannada-English
    c("ನನ್ನ farm ಎಷ್ಟು ಇದೆ", "farm_summary", note="mixed script"),
    c("tomorrow ಮಳೆ ಬರುತ್ತಾ", "weather", note="mixed script"),
    c("ನನ್ನ orders ಏನಾಗಿವೆ", "my_orders", note="mixed script"),
    c("market open ಮಾಡಿ", "navigate:market", note="mixed script"),
    # --- other existing features
    c("ಈ ತಿಂಗಳು ನಾನು ಎಷ್ಟು ಖರ್ಚು ಮಾಡಿದೆ", "expense_summary"),
    c("ನಿನ್ನೆ ಯೂರಿಯಾಗೆ ೧೫೦೦ ರೂಪಾಯಿ ಖರ್ಚು ಮಾಡಿದೆ", "expense_record", note="Kannada digits"),
    c("I spent 1500 rupees on urea yesterday", "expense_record"),
    c("How much did I spend this month?", "expense_summary"),
    c("ನನ್ನ ರಾಗಿ ಎಷ್ಟು ಇಳುವರಿ ಬರಬಹುದು", "harvest_prediction"),
    c("ನನ್ನ ಕೊಯ್ಲು ಯಾವಾಗ", "harvest_prediction"),
    c("ನನ್ನ ಆರ್ಡರ್‌ಗಳು ಏನಾಗಿವೆ", "my_orders", note="zero-width non-joiner"),
    c("ನಾಳೆ ಬೆಳಿಗ್ಗೆ ನೀರು ಹಾಯಿಸಲು ನೆನಪಿಸು", "reminder_create"),
    c("Remind me to spray pesticide tomorrow at 7 am", "reminder_create"),
    c("ನನ್ನ ಟೊಮೆಟೊ ಎಲೆಗಳು ಹಳದಿ ಆಗುತ್ತಿವೆ", "crop_health_help"),
    c("ನನ್ನ ಜಮೀನಿಗೆ ಏನಾದರೂ ಅಪಾಯ ಇದೆಯಾ", "farm_risk"),
    c("ನನ್ನ ದಾಸ್ತಾನು ಎಷ್ಟು ಇದೆ", "inventory"),
    c("ಖರೀದಿದಾರರಿಂದ ಯಾವ ಬೇಡಿಕೆ ಇದೆ", "buyer_opportunities"),
    c("ಮಾರುಕಟ್ಟೆಯಲ್ಲಿ ರಾಗಿ ಎಷ್ಟು ಲಭ್ಯವಿದೆ", "buyer_opportunities", "market_supply", "inventory"),
    c("ನನ್ನ ಆದಾಯ ಯೋಜನೆ ತೋರಿಸು", "income_plans"),
    c("What is my income plan?", "income_plans"),
    c("ರೀ ಅಲೋಕೇಟ್ ಮಾಡಿ 200 ಕೆಜಿ", "allocation_request", "unknown", note="never executes an allocation"),
    c("ಸಹಾಯ", "help"),
    c("ನೀನು ಏನು ಮಾಡಬಲ್ಲೆ", "help"),
    c("Open notifications", "navigate:notifications"),
    c("ಸೂಚನೆಗಳನ್ನು ತೆರೆಯಿರಿ", "navigate:notifications"),
    c("Open reminders", "navigate:reminders"),
    c("ಜ್ಞಾಪನೆಗಳನ್ನು ತೆರೆಯಿರಿ", "navigate:reminders"),
    c("Go home", "navigate:home"),
    c("ಮುಖಪುಟಕ್ಕೆ ಹೋಗು", "navigate:home"),
    c("Open my orders", "navigate:orders"),
    c("ನನ್ನ ಬೇಡಿಕೆಗಳನ್ನು ತೆರೆಯಿರಿ", "navigate:demands"),
    # --- ambiguous, garbled or empty: must NOT be routed to a record tool
    c("ಅದು ಏನು", "unknown"),
    c("ಹೌದು ಹೌದು ಸರಿ", "unknown"),
    c("ಅಲ್ಲಿ ಇದ್ದದ್ದು", "unknown"),
    c("", "unknown", note="silence"),
    c("the the um", "unknown"),
)
