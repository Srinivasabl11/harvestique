# Competitor and reference review (2026-10-14): limited, metadata level

Scope note: this was time-boxed so it would not delay defect fixes. Only public GitHub metadata and file trees were
read (GitHub REST API). No code was copied or run, and the commercial websites were **not** inspected in this
session. Nothing below is a verified feature comparison.

| Reference | Access | What was verified | Notes for Harvestique |
|---|---|---|---|
| agrevolution.in | Not inspected | — | Commercial site; claims would be marketing, not verified implementation |
| ninjacart.com | Not inspected | — | Commercial supply chain; claims would be marketing, not verified implementation |
| github.com/CreativeArun/AgriFlow | Public, **MIT** | 191 files; Java/Spring "FarmFresh_Backend" (with a test folder), a Python "farm-intelligence-api", a JS front end; last push 2026-09-21; 4 stars | The description claims price forecasting, quality assessment, matching and multilingual help. **None of it verified** (no evaluation results seen). Nothing adopted. |
| github.com/om-idiot-engineer/Farm-Nex | **404 Not Found** | — | Repository is missing or private |
| github.com/Mavros-Lykos/AgriSync | Public, **MIT** | 148 files; PHP marketplace; "agents" call **Gemini** (`agents/gemini_client.php`); PHP test scripts; last push 2026-09-06 | Relies on a cloud LLM (cost and API key), which conflicts with ₹0 and offline-first. Its "broker agent" lets an LLM negotiate; Harvestique deliberately keeps allocation deterministic (an LLM never allocates). Nothing adopted. |

## Gaps confirmed in Harvestique itself (not from competitors)
* Calendar reminders from order events (collection dates): partial.
* Account deletion and privacy policy: missing (Play requirement).
* Mandi price data: not integrated. Harvestique never invents prices; a free official source (e.g. Agmarknet /
  data.gov.in) would need licence and freshness checks before use.

## Next step (if wanted)
Read AgriFlow's matching and price-forecast code (MIT) and check for an evaluation. Adopt an idea only if it beats
Harvestique's existing deterministic pool engine on the existing pooling test scenarios.
