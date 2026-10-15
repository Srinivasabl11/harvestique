"""Held-out phrasings, written AFTER the rule changes and never used to tune them (see voice_corpus.py).

Scores on this set are the honest estimate; the development corpus score is optimistic by construction.
"""

from __future__ import annotations

from tests.unit.voice_corpus import Case, c

HELDOUT: tuple[Case, ...] = (
    c("ನನ್ನ ಹತ್ತಿರ ಎಷ್ಟು ಹೊಲ ಇದೆ", "farm_summary"),
    c("ಎಷ್ಟು ಬೆಳೆಗಳು ಇವೆ ನನ್ನ ಜಮೀನಿನಲ್ಲಿ", "farm_summary"),
    c("ನನ್ನ ತೋಟಗಳ ವಿವರ ಹೇಳಿ", "farm_summary"),
    c("tell me about my farms", "farm_summary"),
    c("ನಾಳೆ ಬಿಸಿಲು ಜಾಸ್ತಿ ಇರುತ್ತಾ", "weather"),
    c("ಈ ವಾರ ಮಳೆ ಆಗುತ್ತಾ", "weather"),
    c("is it going to rain this week", "weather"),
    c("ನಮ್ಮ ಗದ್ದೆಯಲ್ಲಿ ಇವತ್ತು ಟೆಂಪರೇಚರ್ ಎಷ್ಟು", "weather"),
    c("ಎರಡು ಎಕರೆ ಟೊಮೆಟೊಗೆ ಎಷ್ಟು ಆದಾಯ ಬರಬಹುದು", "crop_estimate"),
    c("what profit could I make on two acres of ragi", "crop_estimate"),
    c("ಒಂದು ಎಕರೆ ಭತ್ತಕ್ಕೆ ಎಷ್ಟು ಖರ್ಚು ಆಗುತ್ತೆ", "crop_estimate"),
    c("ಕೊಯ್ಲು ಮತ್ತು ಖರೀದಿದಾರರ ಡಿಮ್ಯಾಂಡ್ ಹೋಲಿಕೆ ಮಾಡಿ", "buyer_opportunities"),
    c("is there buyer demand for my expected yield", "buyer_opportunities"),
    c("ಇವತ್ತು ಯಾವ ಕೆಲಸ ಬಾಕಿ ಇದೆ", "reminders_list"),
    c("ನಾಳೆಯ ಜ್ಞಾಪನೆಗಳು ಯಾವುವು", "reminders_list"),
    c("any tasks for today", "reminders_list"),
    c("ನನ್ನ ಹೊಲ ಓಪನ್ ಮಾಡಿ", "navigate:my_farm"),
    c("ಕೊಯ್ಲು ಪುಟಕ್ಕೆ ಹೋಗಿ", "navigate:harvest"),
    c("ಯೋಜನೆ ತೆರೆ", "navigate:planning"),
    c("please open the market", "navigate:market"),
    c("take me home", "navigate:home"),
    c("ಹಿಂದಕ್ಕೆ ಹೋಗಿ", "navigate:back"),
    c("ಕ್ರಾಪ್ ಹೆಲ್ತ್ ಓಪನ್ ಮಾಡಿ", "navigate:crop_health"),
    c("open the notifications page", "navigate:notifications"),
    c("ಆರ್ಡರ್ ಪುಟ ತೆರೆಯಿರಿ", "navigate:orders"),
    c("ಈ ವರ್ಷ ಗೊಬ್ಬರಕ್ಕೆ ಎಷ್ಟು ಖರ್ಚಾಗಿದೆ", "expense_summary"),
    c("ಇವತ್ತು ಕೂಲಿಗೆ ೮೦೦ ರೂಪಾಯಿ ಕೊಟ್ಟೆ", "expense_record"),
    c("ರಾಗಿ ಕೊಯ್ಲು ಯಾವಾಗ ಆಗುತ್ತೆ", "harvest_prediction"),
    c("ನನ್ನ ಬೆಳೆಗೆ ಏನಾದರೂ ರಿಸ್ಕ್ ಇದೆಯಾ", "farm_risk"),
    c("ನಾಡಿದ್ದು ಗೊಬ್ಬರ ಹಾಕಲು ನೆನಪಿಸು", "reminder_create"),
    c("ಮೆಣಸಿನಕಾಯಿ ಎಲೆಯಲ್ಲಿ ಕಪ್ಪು ಕಲೆಗಳಿವೆ", "crop_health_help"),
    c("ಯಾರಾದರೂ ಖರೀದಿದಾರರು ವಿನಂತಿ ಕಳಿಸಿದ್ದಾರಾ", "supply_requests", "buyer_opportunities"),
    c("ನನ್ನ ಡೆಲಿವರಿ ಯಾವ ಹಂತದಲ್ಲಿದೆ", "my_orders", "unknown"),
    c("ಸ್ಟಾಕ್ ಎಷ್ಟು ಉಳಿದಿದೆ", "inventory"),
    c("ಏನು ಹೇಳ್ತಾ ಇದ್ದೆ", "unknown"),
    c("ಸರಿ ಆಯ್ತು", "unknown"),
    c("ಹೂಂ", "unknown"),
    c("ಭತ್ತ ಬೆಳೆಯುವುದು ಹೇಗೆ", "unknown", note="general"),
)
