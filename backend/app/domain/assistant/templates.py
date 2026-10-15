"""Deterministic answer templates in English and Kannada. Numbers come only from tool results.

Kannada strings are plain, farmer-friendly sentences written for this project; they should be reviewed by a
native speaker before production use (see docs/AI_PIPELINE.md).
"""

from __future__ import annotations

GENERAL_AI_DISCLAIMER = {
    "en": "General information from a local AI model, not from your farm records. It can be wrong: check with an agriculture officer before acting.",
    "kn": "ಇದು ಸ್ಥಳೀಯ AI ಮಾದರಿಯ ಸಾಮಾನ್ಯ ಮಾಹಿತಿ, ನಿಮ್ಮ ಜಮೀನಿನ ದಾಖಲೆಗಳಿಂದ ಅಲ್ಲ. ತಪ್ಪಾಗಿರಬಹುದು: ಕ್ರಮ ಕೈಗೊಳ್ಳುವ ಮೊದಲು ಕೃಷಿ ಅಧಿಕಾರಿಯನ್ನು ಸಂಪರ್ಕಿಸಿ.",
}

MIXED_DISCLAIMER = {
    "en": "The first part is from your records. The general advice comes from a local AI model and can be wrong: check with an agriculture officer before acting.",
    "kn": "ಮೊದಲ ಭಾಗ ನಿಮ್ಮ ದಾಖಲೆಗಳಿಂದ. ಸಾಮಾನ್ಯ ಸಲಹೆ ಸ್ಥಳೀಯ AI ಮಾದರಿಯದು, ತಪ್ಪಾಗಿರಬಹುದು: ಕ್ರಮ ಕೈಗೊಳ್ಳುವ ಮೊದಲು ಕೃಷಿ ಅಧಿಕಾರಿಯನ್ನು ಸಂಪರ್ಕಿಸಿ.",
}

# Kannada question, general answer: the local model cannot write reliable Kannada, so it answers in English.
GENERAL_IN_ENGLISH_KN = (
    "ಸ್ಥಳೀಯ AI ಮಾದರಿ ಕನ್ನಡದಲ್ಲಿ ವಿಶ್ವಾಸಾರ್ಹ ಉತ್ತರ ಬರೆಯಲಾರದು, ಆದ್ದರಿಂದ ಈ ಸಾಮಾನ್ಯ ಉತ್ತರ ಇಂಗ್ಲಿಷ್‌ನಲ್ಲಿದೆ. "
    "ಇದು ನಿಮ್ಮ ದಾಖಲೆಗಳಿಂದ ಅಲ್ಲ ಮತ್ತು ತಪ್ಪಾಗಿರಬಹುದು. (The local AI cannot write reliable Kannada, so this general "
    "answer is in English. It is not from your records and can be wrong.)"
)

CATEGORY_KN = {
    "seed": "ಬೀಜ",
    "fertilizer": "ಗೊಬ್ಬರ",
    "pesticide": "ಕೀಟನಾಶಕ",
    "labour": "ಕೂಲಿ",
    "irrigation": "ನೀರಾವರಿ",
    "machinery": "ಯಂತ್ರ",
    "transport": "ಸಾಗಣೆ",
    "other": "ಇತರೆ",
}

DISCLAIMER = {
    "en": "Advisory only. Decisions remain yours.",
    "kn": "ಇದು ಸಲಹೆ ಮಾತ್ರ. ನಿರ್ಧಾರ ನಿಮ್ಮದು.",
}

T: dict[str, dict[str, str]] = {
    "weather": {
        "en": "Weather for {farm}: {rain} mm of rain expected over the next {days} days; highest temperature {tmax}°C. Source: {source}.",
        "kn": "{farm} ಹವಾಮಾನ: ಮುಂದಿನ {days} ದಿನಗಳಲ್ಲಿ ಒಟ್ಟು {rain} ಮಿ.ಮೀ. ಮಳೆ ನಿರೀಕ್ಷೆ; ಗರಿಷ್ಠ ತಾಪಮಾನ {tmax}°C. ಮೂಲ: {source}.",
    },
    "weather_unavailable": {
        "en": "Weather data is not available for {farm} right now ({reason}).",
        "kn": "{farm} ಗೆ ಹವಾಮಾನ ಮಾಹಿತಿ ಈಗ ಲಭ್ಯವಿಲ್ಲ ({reason}).",
    },
    "prediction": {
        "en": "{crop}: predicted harvest {p10}–{p90} kg (middle estimate {p50} kg), confidence {conf}/100 ({level}). Harvest may start around {start}. This is an estimate, not a guarantee.",
        "kn": "{crop}: ಕೊಯ್ಲು ಅಂದಾಜು {p10}–{p90} ಕೆ.ಜಿ. (ಮಧ್ಯಮ ಅಂದಾಜು {p50} ಕೆ.ಜಿ.), ವಿಶ್ವಾಸ {conf}/100. ಕೊಯ್ಲು ಸುಮಾರು {start} ರಿಂದ ಆರಂಭವಾಗಬಹುದು. ಇದು ಅಂದಾಜು ಮಾತ್ರ, ಖಾತರಿ ಅಲ್ಲ.",
    },
    "prediction_insufficient": {
        "en": "{crop}: there is not enough data to predict the quantity yet. Add your own yield estimate or record past harvests.",
        "kn": "{crop}: ಪ್ರಮಾಣವನ್ನು ಅಂದಾಜಿಸಲು ಇನ್ನೂ ಸಾಕಷ್ಟು ಮಾಹಿತಿ ಇಲ್ಲ. ನಿಮ್ಮ ಇಳುವರಿ ಅಂದಾಜು ಅಥವಾ ಹಿಂದಿನ ಕೊಯ್ಲು ದಾಖಲಿಸಿ.",
    },
    "no_prediction": {
        "en": "There is no harvest prediction yet for {crop}. Open the crop and tap 'Predict harvest'.",
        "kn": "{crop} ಬೆಳೆಗೆ ಇನ್ನೂ ಕೊಯ್ಲು ಅಂದಾಜು ಇಲ್ಲ. ಬೆಳೆ ತೆರೆದು 'Predict harvest' ಒತ್ತಿ.",
    },
    "no_cycle": {
        "en": "You have no planned or growing crop yet. Add a crop to one of your plots first.",
        "kn": "ನಿಮ್ಮಲ್ಲಿ ಇನ್ನೂ ಯೋಜಿತ ಅಥವಾ ಬೆಳೆಯುತ್ತಿರುವ ಬೆಳೆ ಇಲ್ಲ. ಮೊದಲು ಒಂದು ಬೆಳೆ ಸೇರಿಸಿ.",
    },
    "farm_summary": {
        "en": "You have {farms} farm(s) with {plots} plot(s), {acres} acres in total, and {crops} planned or growing crop(s){crop_list}.",
        "kn": "ನಿಮ್ಮಲ್ಲಿ {farms} ಜಮೀನು, {plots} ಪ್ಲಾಟ್ (ಒಟ್ಟು {acres} ಎಕರೆ) ಮತ್ತು {crops} ಯೋಜಿತ ಅಥವಾ ಬೆಳೆಯುತ್ತಿರುವ ಬೆಳೆಗಳಿವೆ{crop_list}.",
    },
    "no_farm": {
        "en": "You have not added a farm yet.",
        "kn": "ನೀವು ಇನ್ನೂ ಯಾವುದೇ ಜಮೀನು ಸೇರಿಸಿಲ್ಲ.",
    },
    "risk": {
        "en": "Overall risk for {farm}: {level} ({score}/100), from {assessed} assessed categories.",
        "kn": "{farm} ಒಟ್ಟು ಅಪಾಯ: {level} ({score}/100), {assessed} ಪರಿಶೀಲಿಸಿದ ವಿಭಾಗಗಳ ಆಧಾರದ ಮೇಲೆ.",
    },
    "risk_unknown": {
        "en": "Risk for {farm} cannot be assessed yet: there are no predictions to assess.",
        "kn": "{farm} ಅಪಾಯವನ್ನು ಇನ್ನೂ ಅಂದಾಜಿಸಲು ಸಾಧ್ಯವಿಲ್ಲ: ಯಾವುದೇ ಕೊಯ್ಲು ಅಂದಾಜು ಇಲ್ಲ.",
    },
    "reminders": {
        "en": "You have {n} pending reminders.{items}",
        "kn": "ನಿಮಗೆ {n} ಬಾಕಿ ಜ್ಞಾಪನೆಗಳಿವೆ.{items}",
    },
    "reminder_confirm": {
        "en": 'Shall I add this reminder? "{title}" on {when}. Please confirm.',
        "kn": 'ಈ ಜ್ಞಾಪನೆ ಸೇರಿಸಬೇಕೇ? "{title}" — {when}. ದಯವಿಟ್ಟು ದೃಢೀಕರಿಸಿ.',
    },
    "reminder_need_date": {
        "en": "When should I remind you? Say for example 'tomorrow at 7 am' or 'in 3 days'.",
        "kn": "ಯಾವಾಗ ನೆನಪಿಸಬೇಕು? ಉದಾಹರಣೆಗೆ 'ನಾಳೆ' ಅಥವಾ '3 ದಿನ' ಎಂದು ಹೇಳಿ.",
    },
    "reminder_created": {
        "en": 'Reminder added: "{title}" on {when}.',
        "kn": 'ಜ್ಞಾಪನೆ ಸೇರಿಸಲಾಗಿದೆ: "{title}" — {when}.',
    },
    "inventory": {
        "en": "Your inventory: {n} lots, {available} kg still available to commit (pessimistic p10 estimate), {committed} kg already committed.",
        "kn": "ನಿಮ್ಮ ದಾಸ್ತಾನು: {n} ಲಾಟ್‌ಗಳು, ಇನ್ನೂ {available} ಕೆ.ಜಿ. ಲಭ್ಯ (ಕಡಿಮೆ p10 ಅಂದಾಜು), {committed} ಕೆ.ಜಿ. ಈಗಾಗಲೇ ಬದ್ಧ.",
    },
    "opportunities": {
        "en": "There are {n} open buyer demands for crops you grow.{items}",
        "kn": "ನೀವು ಬೆಳೆಯುವ ಬೆಳೆಗಳಿಗೆ {n} ಖರೀದಿದಾರರ ಬೇಡಿಕೆಗಳಿವೆ.{items}",
    },
    "requests": {
        "en": "{n} supply requests are waiting for your answer.{items}",
        "kn": "ನಿಮ್ಮ ಉತ್ತರಕ್ಕಾಗಿ {n} ಪೂರೈಕೆ ವಿನಂತಿಗಳು ಕಾಯುತ್ತಿವೆ.{items}",
    },
    "orders": {
        "en": "You have {n} orders.{items}",
        "kn": "ನಿಮ್ಮ {n} ಆರ್ಡರ್‌ಗಳಿವೆ.{items}",
    },
    "market_supply": {
        "en": "Future supply on offer from farmers who opted in:{items}",
        "kn": "ರೈತರು ನೀಡುತ್ತಿರುವ ಮುಂದಿನ ಪೂರೈಕೆ:{items}",
    },
    "plans": {
        "en": "You have {n} income plans.{items} Open a plan to see its low, expected and high margins.",
        "kn": "ನಿಮ್ಮ {n} ಆದಾಯ ಯೋಜನೆಗಳಿವೆ.{items} ಕಡಿಮೆ, ನಿರೀಕ್ಷಿತ ಮತ್ತು ಹೆಚ್ಚಿನ ಲಾಭ ನೋಡಲು ಯೋಜನೆ ತೆರೆಯಿರಿ.",
    },
    "plan_result": {
        "en": 'Your plan "{plan}" ({crops} crops): estimated net income {expected} rupees, between {low} and {high} rupees, from the yields, prices and costs you entered. This is an estimate, not a guarantee.',
        "kn": 'ನಿಮ್ಮ "{plan}" ಯೋಜನೆ ({crops} ಬೆಳೆಗಳು): ಅಂದಾಜು ನಿವ್ವಳ ಆದಾಯ {expected} ರೂಪಾಯಿ, {low} ರಿಂದ {high} ರೂಪಾಯಿ ನಡುವೆ, ನೀವು ನಮೂದಿಸಿದ ಇಳುವರಿ, ಬೆಲೆ ಮತ್ತು ಖರ್ಚಿನ ಆಧಾರದ ಮೇಲೆ. ಇದು ಅಂದಾಜು ಮಾತ್ರ, ಖಾತರಿ ಅಲ್ಲ.',
    },
    "plans_empty": {
        "en": "You have {n} income plans, but none has crops yet.{items} Open 'Income plans' and add crops to a plan.",
        "kn": "ನಿಮ್ಮ {n} ಆದಾಯ ಯೋಜನೆಗಳಿವೆ, ಆದರೆ ಯಾವುದರಲ್ಲೂ ಬೆಳೆ ಇಲ್ಲ.{items} 'Income plans' ತೆರೆದು ಬೆಳೆ ಸೇರಿಸಿ.",
    },
    "expenses": {
        "en": "You recorded {total} rupees of expenses{what}{when}, in {entries}.{items}",
        "kn": "ನೀವು{when}{what} ಒಟ್ಟು {total} ರೂಪಾಯಿ ಖರ್ಚು ದಾಖಲಿಸಿದ್ದೀರಿ, {n} ನಮೂದುಗಳಲ್ಲಿ.{items}",
    },
    "expenses_none": {
        "en": "No expenses are recorded{what}{when}.",
        "kn": "{when}{what} ಯಾವುದೇ ಖರ್ಚು ದಾಖಲಾಗಿಲ್ಲ.",
    },
    "expense_confirm": {
        "en": "Shall I record an expense of {amount} rupees for {category} on {date} at {farm}? Please confirm.",
        "kn": "{farm} ಗೆ {date} ರಂದು {category} ಗಾಗಿ {amount} ರೂಪಾಯಿ ಖರ್ಚು ದಾಖಲಿಸಬೇಕೇ? ದಯವಿಟ್ಟು ದೃಢೀಕರಿಸಿ.",
    },
    "expense_need_amount": {
        "en": "How much did you spend? Say for example 'I spent 500 rupees on fertilizer today'.",
        "kn": "ಎಷ್ಟು ಖರ್ಚು ಮಾಡಿದಿರಿ? ಉದಾಹರಣೆಗೆ 'ಇಂದು ಗೊಬ್ಬರಕ್ಕೆ 500 ರೂಪಾಯಿ ಖರ್ಚು ಮಾಡಿದೆ' ಎಂದು ಹೇಳಿ.",
    },
    "expense_need_category": {
        "en": "What was the {amount} rupees spent on: seed, fertilizer, pesticide, labour, irrigation, machinery or transport?",
        "kn": "{amount} ರೂಪಾಯಿ ಯಾವುದಕ್ಕೆ ಖರ್ಚಾಯಿತು: ಬೀಜ, ಗೊಬ್ಬರ, ಕೀಟನಾಶಕ, ಕೂಲಿ, ನೀರಾವರಿ, ಯಂತ್ರ ಅಥವಾ ಸಾಗಣೆ?",
    },
    "expense_created": {
        "en": "Recorded: {amount} rupees for {category} on {date}.",
        "kn": "ದಾಖಲಿಸಲಾಗಿದೆ: {date} ರಂದು {category} ಗಾಗಿ {amount} ರೂಪಾಯಿ.",
    },
    "general_kannada_unavailable": {
        "en": "I cannot yet give reliable general farming answers in Kannada. Please ask your Raitha Samparka Kendra or agriculture officer. I can tell you about your weather, expenses, harvest predictions, income plans and reminders.",
        "kn": "ಸಾಮಾನ್ಯ ಕೃಷಿ ಪ್ರಶ್ನೆಗಳಿಗೆ ಕನ್ನಡದಲ್ಲಿ ವಿಶ್ವಾಸಾರ್ಹ ಉತ್ತರ ನೀಡಲು ನನಗೆ ಇನ್ನೂ ಸಾಧ್ಯವಿಲ್ಲ. ದಯವಿಟ್ಟು ರೈತ ಸಂಪರ್ಕ ಕೇಂದ್ರ ಅಥವಾ ಕೃಷಿ ಅಧಿಕಾರಿಯನ್ನು ಕೇಳಿ. ನಿಮ್ಮ ಹವಾಮಾನ, ಖರ್ಚು, ಕೊಯ್ಲು ಅಂದಾಜು, ಆದಾಯ ಯೋಜನೆ ಮತ್ತು ಜ್ಞಾಪನೆಗಳ ಬಗ್ಗೆ ನಾನು ಹೇಳಬಲ್ಲೆ.",
    },
    "crop_health": {
        "en": "To check crop health, take a clear photo of the affected leaves and use 'Crop health' on the crop. The result is a probability-based suggestion, not a diagnosis; contact an agriculture officer to confirm.",
        "kn": "ಬೆಳೆಯ ಆರೋಗ್ಯ ಪರಿಶೀಲಿಸಲು ಎಲೆಯ ಸ್ಪಷ್ಟ ಫೋಟೋ ತೆಗೆದು 'Crop health' ಬಳಸಿ. ಫಲಿತಾಂಶ ಸಂಭಾವ್ಯತೆಯ ಸಲಹೆ ಮಾತ್ರ, ರೋಗನಿರ್ಣಯ ಅಲ್ಲ; ಖಚಿತಪಡಿಸಲು ಕೃಷಿ ಅಧಿಕಾರಿಯನ್ನು ಸಂಪರ್ಕಿಸಿ.",
    },
    "allocation_refused": {
        "en": "I can't decide or change allocation quantities. The Harvest Pool engine sets them from the predicted (p10) supply, and farmers accept or decline requests themselves.",
        "kn": "ಹಂಚಿಕೆ ಪ್ರಮಾಣಗಳನ್ನು ನಾನು ನಿರ್ಧರಿಸುವುದಿಲ್ಲ ಅಥವಾ ಬದಲಾಯಿಸುವುದಿಲ್ಲ. ಹಾರ್ವೆಸ್ಟ್ ಪೂಲ್ ವ್ಯವಸ್ಥೆ ಅಂದಾಜಿನ ಆಧಾರದ ಮೇಲೆ ಅವುಗಳನ್ನು ಲೆಕ್ಕ ಹಾಕುತ್ತದೆ; ರೈತರೇ ವಿನಂತಿಗಳನ್ನು ಒಪ್ಪುತ್ತಾರೆ ಅಥವಾ ನಿರಾಕರಿಸುತ್ತಾರೆ.",
    },
    "help": {
        "en": "I can tell you about weather, harvest predictions, farm risk, your expenses, income plans, reminders, your inventory, buyer demand and your supply requests. After you confirm, I can add reminders and record expenses.",
        "kn": "ನಾನು ಹವಾಮಾನ, ಕೊಯ್ಲು ಅಂದಾಜು, ಜಮೀನಿನ ಅಪಾಯ, ನಿಮ್ಮ ಖರ್ಚು, ಆದಾಯ ಯೋಜನೆಗಳು, ಜ್ಞಾಪನೆಗಳು, ದಾಸ್ತಾನು, ಖರೀದಿದಾರರ ಬೇಡಿಕೆ ಮತ್ತು ಪೂರೈಕೆ ವಿನಂತಿಗಳ ಬಗ್ಗೆ ಹೇಳಬಲ್ಲೆ. ನೀವು ದೃಢೀಕರಿಸಿದ ನಂತರ ಜ್ಞಾಪನೆ ಸೇರಿಸಬಲ್ಲೆ ಮತ್ತು ಖರ್ಚು ದಾಖಲಿಸಬಲ್ಲೆ.",
    },
    "unknown": {
        "en": "Sorry, I did not understand. You can ask about weather, harvest, expenses, income plans, reminders, risk or buyers.",
        "kn": "ಕ್ಷಮಿಸಿ, ನನಗೆ ಅರ್ಥವಾಗಲಿಲ್ಲ. ಹವಾಮಾನ, ಕೊಯ್ಲು, ಖರ್ಚು, ಆದಾಯ ಯೋಜನೆ, ಜ್ಞಾಪನೆ, ಅಪಾಯ ಅಥವಾ ಖರೀದಿದಾರರ ಬಗ್ಗೆ ಕೇಳಿ.",
    },
    "unknown_no_ai": {
        "en": "I can answer questions about your weather, harvest, expenses, income plans, reminders, risk and buyers. General questions need the local AI model (Ollama), which is not running on the server right now.",
        "kn": "ನಿಮ್ಮ ಹವಾಮಾನ, ಕೊಯ್ಲು, ಖರ್ಚು, ಆದಾಯ ಯೋಜನೆ, ಜ್ಞಾಪನೆ, ಅಪಾಯ ಮತ್ತು ಖರೀದಿದಾರರ ಬಗ್ಗೆ ಉತ್ತರಿಸಬಲ್ಲೆ. ಸಾಮಾನ್ಯ ಪ್ರಶ್ನೆಗಳಿಗೆ ಸ್ಥಳೀಯ AI ಮಾದರಿ (Ollama) ಬೇಕು, ಅದು ಈಗ ಸರ್ವರ್‌ನಲ್ಲಿ ಚಾಲನೆಯಲ್ಲಿಲ್ಲ.",
    },
    "weather_day": {
        "en": "Weather for {farm} {when} ({date}): {tmin}–{tmax}°C, about {rain} mm of rain. Forecast fetched {fetched} ({status}); forecasts can change.",
        "kn": "{farm} ಹವಾಮಾನ {when} ({date}): {tmin}–{tmax}°C, ಸುಮಾರು {rain} ಮಿ.ಮೀ. ಮಳೆ. ಮುನ್ಸೂಚನೆ ಪಡೆದದ್ದು {fetched} ({status}); ಮುನ್ಸೂಚನೆ ಬದಲಾಗಬಹುದು.",
    },
    "unclear": {
        "en": "Sorry, I could not make that out clearly. Please say it again or type it. For example: 'What is crop rotation?', 'How many farms do I have?' or 'Open Market'.",
        "kn": "ಕ್ಷಮಿಸಿ, ಅದು ಸ್ಪಷ್ಟವಾಗಿ ಅರ್ಥವಾಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ಮತ್ತೆ ಹೇಳಿ ಅಥವಾ ಟೈಪ್ ಮಾಡಿ. ಉದಾಹರಣೆಗೆ: 'ಬೆಳೆ ಸರದಿ ಎಂದರೇನು?', 'ನನಗೆ ಎಷ್ಟು ಜಮೀನು ಇದೆ?' ಅಥವಾ 'ಮಾರುಕಟ್ಟೆ ತೆರೆಯಿರಿ'.",
    },
    "suitability_need_crop": {
        "en": "Which crop do you want to grow? Say, for example: 'Can I grow carrots on my farm?'",
        "kn": "ಯಾವ ಬೆಳೆ ಬೆಳೆಯಲು ಬಯಸುತ್ತೀರಿ? ಉದಾಹರಣೆಗೆ: 'ನನ್ನ ಜಮೀನಿನಲ್ಲಿ ಕ್ಯಾರೆಟ್ ಬೆಳೆಯಬಹುದೇ?'",
    },
    "suitability_crop": {
        "en": "{crop}: season {season}, about {days} days, water need about {water} mm (crop catalogue).",
        "kn": "{crop}: ಹಂಗಾಮು {season}, ಸುಮಾರು {days} ದಿನಗಳು, ನೀರಿನ ಅಗತ್ಯ ಸುಮಾರು {water} ಮಿ.ಮೀ. (ಬೆಳೆ ಪಟ್ಟಿ).",
    },
    "suitability_farm": {
        "en": "Your farm {farm}: place {place}; soil {soils}; irrigation {irrigation} (your records).",
        "kn": "ನಿಮ್ಮ ಜಮೀನು {farm}: ಸ್ಥಳ {place}; ಮಣ್ಣು {soils}; ನೀರಾವರಿ {irrigation} (ನಿಮ್ಮ ದಾಖಲೆಗಳು).",
    },
    "suitability_missing": {
        "en": "To judge properly, add or check: {missing}.",
        "kn": "ಸರಿಯಾಗಿ ತಿಳಿಯಲು ಸೇರಿಸಿ ಅಥವಾ ಪರಿಶೀಲಿಸಿ: {missing}.",
    },
    "suitability_no_verdict": {
        "en": "I can't give a definite yes or no from these records; your local Raitha Samparka Kendra can advise for your field.",
        "kn": "ಈ ದಾಖಲೆಗಳಿಂದ ಖಚಿತವಾಗಿ ಹೌದು ಅಥವಾ ಇಲ್ಲ ಎನ್ನಲಾಗದು; ನಿಮ್ಮ ಹೊಲಕ್ಕೆ ಸ್ಥಳೀಯ ರೈತ ಸಂಪರ್ಕ ಕೇಂದ್ರ ಸಲಹೆ ನೀಡಬಹುದು.",
    },
    "navigate": {"en": "Opening {screen}.", "kn": "{screen} ತೆರೆಯುತ್ತಿದ್ದೇನೆ."},
    "navigate_unavailable": {
        "en": "{screen} is not part of your account type, so I can't open it.",
        "kn": "{screen} ನಿಮ್ಮ ಖಾತೆ ಪ್ರಕಾರದಲ್ಲಿ ಇಲ್ಲ, ಆದ್ದರಿಂದ ತೆರೆಯಲು ಆಗುವುದಿಲ್ಲ.",
    },
    "not_for_role": {
        "en": "That is not available for your account type.",
        "kn": "ಅದು ನಿಮ್ಮ ಖಾತೆ ಪ್ರಕಾರಕ್ಕೆ ಲಭ್ಯವಿಲ್ಲ.",
    },
    "tool_failed": {
        "en": "I could not get that information right now. Please try again later.",
        "kn": "ಆ ಮಾಹಿತಿಯನ್ನು ಈಗ ಪಡೆಯಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ನಂತರ ಪ್ರಯತ್ನಿಸಿ.",
    },
}


def render(key: str, lang: str, **values: object) -> str:
    table = T[key]
    return table.get(lang, table["en"]).format(**values)


SCREENS = {
    "back": ("the previous screen", "ಹಿಂದಿನ ಪುಟ"),
    "home": ("Home", "ಮುಖಪುಟ"),
    "my_farm": ("My Farm", "ನನ್ನ ಜಮೀನು"),
    "market": ("Market", "ಮಾರುಕಟ್ಟೆ"),
    "harvest": ("Harvest", "ಕೊಯ್ಲು"),
    "reminders": ("Reminders", "ಜ್ಞಾಪನೆಗಳು"),
    "crop_health": ("Crop health", "ಬೆಳೆ ಆರೋಗ್ಯ"),
    "planning": ("Income planning", "ಆದಾಯ ಯೋಜನೆ"),
    "notifications": ("Notifications", "ಸೂಚನೆಗಳು"),
    "orders": ("Orders", "ಆರ್ಡರ್‌ಗಳು"),
    "demands": ("My demands", "ನನ್ನ ಬೇಡಿಕೆಗಳು"),
}


def screen_name(key: str, lang: str) -> str:
    en, kn = SCREENS.get(key, (key, key))
    return kn if lang == "kn" else en
