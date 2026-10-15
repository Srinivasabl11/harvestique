# Assistant evaluation: general knowledge, farm tools and English/Kannada parity (2026-10-14)

**Result:** on the live server with the real local model (`llama3.2:3b`), the 12 request types in both languages
went from **14/26 correct to 25/26**. Incorrect or hallucinated answers went from **6 to 0**. The one remaining
failure is a Kannada follow-up that timed out under load; it answered correctly on 2 of 2 re-runs.

These are typed transcripts. **Phone speech recognition and Kannada TTS were not tested**: no device session and no
recordings.

## Method
* **Live run:** the real assistant service inside the running backend container, the real Ollama model and the real
  database.
  * Account: the labelled test farmer "Stage3 Live Test Farmer (Claude)": 1 farm, no plots, crops, plans or
    reminders.
  * The session was rolled back, so nothing was saved.
  * Script: `scratchpad/repro_assistant.py`.
  * Raw results: `harvestique-eval-data\results\assistant_live_{baseline,final,final2}_20261014.json`.
* **12 request types × English and Kannada:** general farming, general education, my farms and crops, saved income
  plans, one-acre cost/profit, crop suitability, weather tomorrow, harvest vs buyer demand, reminders, navigation,
  garbled request, and a follow-up (with its first question).
* **Judging:** I judged correctness by reading each answer. Wrong tool, wrong language/voice, invented facts, and
  unsupported claims all counted as failures.

## Results
| | Baseline | Final |
|---|---|---|
| Correct answers (English) | 10/13 | 13/13 |
| Correct answers (Kannada) | 4/13 | 12/13 (follow-up timed out; 2/2 on re-run) |
| Correct routing (intent / tool) | 21/26 | 26/26 |
| General-question answers (4 per language) | English 4/4, **Kannada 0/4** | English 4/4, Kannada 3/4 (timeout) |
| Incorrect or hallucinated answers | **6** | **0** |
| Kannada general answer latency (median) | 27.6 s (garbled) | 9.0 s glossary path; about 30 s when translated by the model |
| English general answer latency (median) | 11.2 s | 10.7 s |

**Baseline failures, from the real output:**
* **Kannada general questions:** the model wrote ungrammatical, wrong Kannada ("crop rotation" explained as
  releasing seed from the crop). The reply was labelled English, so the phone would read Kannada text with the English
  voice.
* **"My farms and crops" in Kannada:** not understood.
* **One-acre cucumber cost and profit (both languages):** answered with "You have 0 income plans".
* **"Can I grow carrots on my farm?":** English said "Yes, you can grow carrots on your farm" with no farm data;
  Kannada said "didn't understand".
* **"Weather tomorrow":** answered with 7-day totals.
* **Garbled Kannada:** a confident nonsense answer.

## Root causes and fixes
| # | Root cause (measured) | Fix |
|---|---|---|
| 1 | `llama3.2:3b` **cannot read Kannada**: asked directly, it answered "ಬೆಳೆ ಸರದಿ" (crop rotation) as "Bajra sari crop insurance" and photosynthesis as "photocatalytic synthesis". Asked to write Kannada, it produced garbled text. | Kannada general questions are **translated to English first**, then answered in English. A small Kannada→English farming glossary covers the terms both installed models mistranslate; "<term> ಎಂದರೇನು" needs no model at all. The reply shows **"ನಾನು ಅರ್ಥಮಾಡಿಕೊಂಡ ಪ್ರಶ್ನೆ / Understood as: …"**, so a wrong reading is visible. |
| 2 | Wrong-language output (Kannada text labelled English) and mixed-script output | Output is checked: Kannada in an English answer triggers one retry, then the answer is dropped. Other scripts (Devanagari, Sinhala, Gujarati…) are dropped. |
| 3 | Garbled speech got answered | The model may reply UNCLEAR, which gives a fixed clarification in the user's language. |
| 4 | No calculation path: one-acre estimates fell into "saved plans" | New `crop_estimate`. It uses the **existing income calculator** (`PlanningService.calculate`). Yield comes from the farmer's saved plan or the catalogue reference (labelled "not your farm"); price and cost come from what the farmer said or their plan. **Missing price or cost is asked for, never guessed.** Kannada word order ("ಕೆಜಿಗೆ 10 ರೂಪಾಯಿ", "ಎಕರೆಗೆ 30000 ಖರ್ಚು") is parsed. Farmers only. |
| 5 | No suitability path | New `crop_suitability`: the crop's catalogue needs, plus the farm's recorded place, soil and irrigation, plus what is missing, plus labelled general AI advice. **Never a yes/no verdict.** |
| 6 | "Weather tomorrow" gave weekly totals; freshness not stated | Today/tomorrow answers for that day (IST), with the fetch time and "latest" or "older saved forecast, may be out of date". Unavailable weather is never shown as numbers. |
| 7 | Kannada farm summary missed "ನನ್ನ ಜಮೀನುಗಳು **ಮತ್ತು** ಬೆಳೆಗಳು ಯಾವುವು" | Up to 3 words allowed between the noun and the verb |

**Evidence for decision 1 (installed models only, nothing downloaded):**
* **Writing Kannada:** `gemma3:4b` writes more fluent Kannada than `llama3.2:3b`, but still had wrong facts (crop
  rotation as "managing farm work"; soil pH as "amount of oxygen") and mixed Sinhala, Gujarati and Bengali
  characters into answers.
* **Understanding Kannada (translation test):** both models got 6 of 8 questions right, and both missed "ಬೆಳೆ
  ಸರದಿ" and "ಎಲೆ ಮುರುಟು" (the glossary now covers both).
* **Memory:** only about 2.1–2.5 GB of RAM was free, so running a second model alongside the assistant model is not
  safe on this PC.
* **Decision:** keep `llama3.2:3b`, translate first, answer in English. Kannada **record** answers, estimates,
  suitability, weather, navigation and clarifications are Kannada templates, spoken with the Kannada voice.

## Automated tests (typed transcripts; scripted model)
* New file `tests/integration/test_assistant_routing.py` (18 tests). It covers all 12 types in both languages,
  including:
  * the wrong-language retry and drop;
  * translation, and glossary replacement before translation;
  * estimates that ask for missing inputs;
  * estimate numbers checked against the `/planning/calculate` endpoint;
  * estimates refused for buyers;
  * suitability with and without a farm;
  * weather fresh and unavailable;
  * clarification for garbled text;
  * model failure;
  * follow-ups in both languages.
* Voice corpus expectations were updated: suitability → `crop_suitability`, estimates → `crop_estimate`. **Both
  corpora are now development sets**: the rules were adjusted with them in view, so their 100 % is not an
  accuracy estimate.
* Assistant suites: 195 passed. Full backend suite: **1607 passed** (was 1588); Flutter 148 passed.

## Not tested, and limits
* **Phone microphone (Android recogniser, kn-IN/en-IN) and Kannada TTS:** not tested; this needs a phone session.
  The app checks that a Kannada recogniser exists and shows the transcript plus a text box.
* **Latency:** a Kannada general question that needs model translation took about 30 s on this CPU, and once 61 s
  (timeout, safe failure). English general answers take about 11 s; record answers under 1 s.
* **English answers to Kannada general questions:** these are by design, with a Kannada note. A better
  Kannada-capable local model would need a download, which needs approval.
* **Glossary:** 31 entries, written for this project; should be reviewed by a native speaker.
* **Suitability:** uses only what is recorded. The test farm had no soil or irrigation recorded, so the answer asked
  for them.

---

# Part 2: examples, follow-up numbers and estimates (same day)

## The phone report, reproduced on the live server
After an income question for one acre, the follow-up was "For example 20 kg and ₹50,000" (or the Kannada
equivalent). Baseline, real model, raw results in
`harvestique-eval-data\results\assistant_estimate_followups_baseline_20261014.json`:

| Follow-up | Baseline answer |
|---|---|
| "For example 20 kg and ₹50,000" (EN, twice) | General AI path, **invented figures**: "Typical income from one acre of tomatoes … ₹50,000 to ₹75,000" |
| "ಉದಾಹರಣೆಗೆ 20 ಕೆಜಿ ಮತ್ತು 50,000 ರೂಪಾಯಿ" | Echo: "50,000 rupees. Numbers here are approximate…" |
| "ಉದಾಹರಣೆಗೆ ಕೆಜಿಗೆ 20 ರೂಪಾಯಿ, ಖರ್ಚು 50000" | **Past-expenses tool**: "no expenses recorded" |

## Root causes
1. **The estimate was not a follow-up topic.** `crop_estimate` was not in the follow-up set, so a follow-up with
   numbers fell to the general model, or to past expenses when it contained "ಖರ್ಚು".
2. **The estimate read only the current message.** The crop, acres and numbers from earlier turns (which the app
   does send as history, with each reply's intent) were ignored.
3. **Numbers were only found in a few fixed phrasings.** "50,000", "1,20,000", "50 ಸಾವಿರ", "1.5 lakh",
   quintal/tonne and gunta were not read. A number with no stated meaning was silently ignored instead of asked
   about.

The app was not at fault: the chat screen sends the last 8 turns with each reply's intent, and "Clear
conversation" empties them.

## Changes
* **New `app/domain/assistant/estimate.py`.** It works out what each number IS, from words in the same clause:
  * price per kg (also per quintal or tonne, converted);
  * harvest (kg, quintal or tonne, per acre or in total);
  * cost or income (per acre or total);
  * acres (also guntas, and "one/ಒಂದು" acre).
  It reads English and Kannada word order, Kannada digits, Indian grouping, and lakh/thousand/ಸಾವಿರ. A number
  without a stated meaning is **unclear** and is asked about, never assumed. Messages are merged oldest first, the
  newest correction wins, and a number is no longer unclear once a later message states it.
* **Service.** After an estimate reply, a follow-up with numbers or a crop name continues the estimate, including
  messages the rules would send to expenses, saved plans or the harvest forecast. Anything else (reminders,
  navigation, "what is crop rotation?") routes normally. Naming a different crop starts the estimate afresh, so
  tomato's price is not reused for onion. An income/profit question naming a crop (and not a "plan") is an
  estimate, not the saved-plan list.
* **Answer.** Either one question about everything that's missing or unclear (acres, crop or harvest, price,
  cost, and per-acre-or-total when the area is more than 1 acre), or a calculation with the working shown:
  harvest × price = income; cost per acre × acres; income − cost = profit.
  * The numbers come from the existing income calculator.
  * Each input is labelled: what you said, your saved plan, or the catalogue estimate ("not your farm").
  * The calculator's cautious case (low harvest, 10 % cost overrun) is shown. Losses are shown as "−₹… (a loss)".
  * A harvest more than 10× below or 3× above the catalogue range triggers a unit check ("20 kg per acre is far
    from the usual 6,500–13,500 kg for Tomato; 1 quintal = 100 kg").
  * The language model is never called for an estimate (tests fail if it is).
* The old single-message estimate code and its templates were removed, leaving one implementation.

## Results
Live server, real model, same test farmer, rolled back. Raw results:
`assistant_estimate_followups_final_20261014.json`.

| Follow-up | Final answer |
|---|---|
| "For example 20 kg and ₹50,000" (EN) and the Kannada version | Asks: is 20 kg the harvest (per acre or total)? Is ₹50,000 your cost, your income or the price per kg? (Kannada in Kannada) |
| "20 quintal per acre is the harvest, 50000 is the total cost, price 25 rupees per kg" | 2,000 kg × ₹25 = ₹50,000; cost ₹50,000; profit ₹0; cautious case −₹5,000 (a loss) |
| "sorry, the price is 30 rupees per kg" | ₹60,000 − ₹50,000 = ₹10,000 (the result changed; not repeated) |
| "ಉದಾಹರಣೆಗೆ ಕೆಜಿಗೆ 20 ರೂಪಾಯಿ, ಖರ್ಚು 50000" | Kannada calculation with the catalogue harvest 6,500–13,500 kg (labelled): income ₹1,30,000–₹2,70,000 (expected ₹2,00,000); profit ₹1,50,000 |
| "what is crop rotation?" after the estimate | Normal general answer |

All figures were checked by hand. In all 16 live turns, no estimate turn called the model, and no number was
invented.

**Automated tests (typed transcripts):**
* `tests/unit/test_estimate_parsing.py` (19): both phone examples, units, Indian formats, Kannada digits, unclear
  numbers, merging and corrections.
* `tests/integration/test_assistant_estimates.py` (9), in English and Kannada:
  * the exact phone scenario (the second reply is checked to differ from the first);
  * missing inputs asked in one question;
  * income − cost given directly;
  * corrections and quintal conversion changing the result;
  * per-acre-or-total question;
  * a new crop resetting the estimate;
  * other questions after an estimate routing normally;
  * an empty history not inheriting old numbers;
  * saved plans vs estimates;
  * buyers refused.
* Assistant suites: 223 passed. Full backend suite: **1635 passed**; Flutter 148 passed.

**Not tested:** spoken input on the phone (recogniser transcripts of numbers written in words, such as
"ಐವತ್ತು ಸಾವಿರ"), and Kannada TTS of the calculation text.

**Limits:**
* Spelled-out numbers other than simple acre words ("fifty thousand", "ಐವತ್ತು ಸಾವಿರ") are not read, so the assistant
  asks for digits.
* "Yes" in answer to a clarification is not understood; the person must restate the number with its meaning.
* Predictions (weather, harvest forecast) stay separate tools and are labelled as forecasts and estimates.
