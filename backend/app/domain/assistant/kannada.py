"""Kannada general questions -> English, for the local model (which cannot read Kannada reliably: measured on
2026-10-14, llama3.2:3b answered "ಬೆಳೆ ಸರದಿ ಎಂದರೇನು" (what is crop rotation?) as if it asked about "Bajra sari crop
insurance"). Farming terms both installed models mistranslate are replaced first from this glossary; "<term>
ಎಂದರೇನು" ("what is <term>?") becomes an English question without any model.

The glossary was written for this project and should be reviewed by a native speaker (docs/ASSISTANT_EVAL_2026-10-14.md).
"""

from __future__ import annotations

import re

# longest entries first so "ಎಲೆ ಮುರುಟು ರೋಗ" wins over "ಮುರುಟು ರೋಗ"
GLOSSARY: dict[str, str] = {
    "ಬೆಳೆ ಸರದಿ": "crop rotation",
    "ಬೆಳೆ ಪರಿವರ್ತನೆ": "crop rotation",
    "ದ್ಯುತಿಸಂಶ್ಲೇಷಣೆ": "photosynthesis",
    "ಮಣ್ಣಿನ ಪಿಎಚ್": "soil pH",
    "ಮಣ್ಣಿನ ರಸಸಾರ": "soil pH",
    "ಮಣ್ಣು ಪರೀಕ್ಷೆ": "soil test",
    "ಎಲೆ ಮುರುಟು ರೋಗ": "leaf curl disease",
    "ಮುರುಟು ರೋಗ": "leaf curl disease",
    "ಎಲೆ ಮುರುಟು": "leaf curl",
    "ಎಲೆ ಚುಕ್ಕೆ ರೋಗ": "leaf spot disease",
    "ಎಲೆ ಚುಕ್ಕೆ": "leaf spot",
    "ಬೂದಿ ರೋಗ": "powdery mildew",
    "ಬೆಂಕಿ ರೋಗ": "blast disease",
    "ಸೊರಗು ರೋಗ": "wilt disease",
    "ಕೊಳೆ ರೋಗ": "rot disease",
    "ಎರೆಹುಳು ಗೊಬ್ಬರ": "vermicompost",
    "ಹಸಿರೆಲೆ ಗೊಬ್ಬರ": "green manure",
    "ಕಾಂಪೋಸ್ಟ್ ಗೊಬ್ಬರ": "compost",
    "ಸಾವಯವ ಕೃಷಿ": "organic farming",
    "ಹನಿ ನೀರಾವರಿ": "drip irrigation",
    "ತುಂತುರು ನೀರಾವರಿ": "sprinkler irrigation",
    "ಮಿಶ್ರ ಬೆಳೆ": "mixed cropping",
    "ಅಂತರ ಬೆಳೆ": "intercropping",
    "ಬೀಜೋಪಚಾರ": "seed treatment",
    "ಸಾರಜನಕ": "nitrogen",
    "ರಂಜಕ": "phosphorus",
    "ಪೊಟ್ಯಾಷ್": "potash",
    "ಕೀಟನಾಶಕ": "pesticide",
    "ಕಳೆನಾಶಕ": "herbicide",
    "ಮಣ್ಣಿನ ಸವಕಳಿ": "soil erosion",
    "ಮಳೆ ನೀರು ಕೊಯ್ಲು": "rainwater harvesting",
}
_TERMS = sorted(GLOSSARY, key=len, reverse=True)
_WHAT_IS = re.compile(r"^(?P<term>.+?)\s*(ಎಂದರೇನು|ಎಂದರೆ ಏನು|ಅಂದರೆ ಏನು|ಅಂದ್ರೆ ಏನು)\s*[?？]?$")


def gloss(text: str) -> str:
    """Replace known farming terms with English (also inside inflected words: 'ಬೆಳೆ ಸರದಿಯಿಂದ')."""
    for term in _TERMS:
        text = text.replace(term, f" {GLOSSARY[term]} ")
    return " ".join(text.split())


def english_question(text: str) -> str | None:
    """'ಬೆಳೆ ಸರದಿ ಎಂದರೇನು' -> 'What is crop rotation?' when the whole term is in the glossary; otherwise None."""
    m = _WHAT_IS.match(" ".join(text.split()))
    if m and (term := m.group("term").strip()) in GLOSSARY:
        return f"What is {GLOSSARY[term]}?"
    return None
