# Phone test report: Samsung SM-M156B (Android 16), session 2026-10-13 23:55 to 2026-10-14 01:20 IST

Evidence levels: **Phone** = done on the real phone through the app's screens (driven over ADB; screenshots and
server logs checked), **API** = direct calls to the live server, **Automated** = backend pytest / Flutter tests.

## Setup and safety
* ADB authorised (`device`), app `com.example.harvestique` updated with `adb install -r` only. `firstInstallTime`
  stayed `2026-10-09 00:49:53` on every install, so app data was never cleared. The app was found signed out and was
  left signed out.
* Only labelled test accounts were used: farmer **Stage3 Live Test Farmer (Claude)** (+91 97758 23658, farm "Stage3
  Test Farm") and a new buyer **Stage3 Phone Test Buyer (Claude)** (+91 96775 55730, created for this run).
* Market tests used **Browntop Millet**, which no other account grows; the database confirmed that only the test
  farmer received notifications. No real account was notified. No SMS was sent (development OTP mode, labelled on
  screen).
* Your personal photos appeared in the Google Photos picker; they were not opened or selected, and the one screenshot
  of that screen was deleted unviewed. Test photos were pushed to `Pictures/HarvestiqueTest` and removed afterwards
  (media index checked: no entries left).
* One unintended action: a mis-aimed tap focused the search box of another app (Perplexity) for a moment; nothing was
  typed or sent. The test helper now refuses to tap or type unless Harvestique is in front.

## Problems found and fixed during the run
| # | Problem (seen on the phone) | Root cause | Fix | Verified |
|---|---|---|---|---|
| 1 | App showed "Cannot reach the Harvestique server" | PC Wi-Fi address changed after a restart (192.168.29.200 -> .100); the APK has the address built in | APK rebuilt for `http://192.168.29.100:8000/api/v1` (only change) | Phone: sign-in works |
| 2 | **Pull-to-refresh and Retry did nothing** on every list screen | `setState(() => _future = next)` returns a Future; debug builds throw (phone log: "setState() callback argument returned a Future") and skip the rebuild | Block-bodied `setState` in `Reloadable` and two crop-list Retry buttons | Automated (new tests reproduce and pass); phone log: no Flutter errors after the fix |
| 3 | Harvest showed "Deliveries you accepted: None yet" right after accepting an order | Tabs are built once at sign-in (IndexedStack) and never reloaded | A tab reloads each time it is opened (farmer and buyer shells) | Phone: after an app restart the delivery shows; fix build installed |
| 4 | Weather listed "yesterday" first and an hour already past (just after midnight) | Server used the UTC date as "today" (UTC is a day behind IST until 05:30) plus cached forecasts | Farm-local (IST) today in the weather service; past days and hours filtered | Phone: outlook starts "Today", hours start at the current hour |
| 5 | Notification time "13 Oct 2026 00:25" for a 14 Oct 00:25 event | `dateTime()` took the date from the UTC string, the time from local | Date and time both local | Phone: shows 14 Oct 2026 00:25 |
| 6 | "Cancel order" cancelled a real order with one tap | No confirmation | Confirmation dialog ("Keep order" / "Cancel order") | Automated (new widget test) |
| 7 | Bell announced only "2" to screen readers | Badge text replaced the label | "Notifications, 2 unread" | Phone (accessibility tree) |
| 8 | Note label overlapped the crop dropdown (field work and expense forms) | No spacing | 16 px gap | Automated |
| 9 | Messages showed developer text "(is_active=false)"; crop-delete message wrong for crops with predictions/orders | Server wording | Plain wording | Automated (916 farm/crop tests) |
| 10 | Mixed AI answer started with "However, …" after a filtered sentence | Leading connective left behind | Stripped | Automated |

## Results by request item
| Item | Result | Evidence |
|---|---|---|
| 1 ADB, launch | **Passed** | Phone |
| 3 Field work log (test farm) | **Passed**: empty state, validation ("Choose what work was done."), add Irrigation with note (201), edit to Weeding (200), delete with Keep/Delete confirmation (204), back to empty state; test entry removed | Phone + server log |
| 4 Catalogue | **Passed**: "All (88)", "Plantation crops (6)" Arecanut, Cashew, Coconut, Coffee, Rubber, Tea with Kannada names; search "millet" shows Barnyard, Browntop, Kodo, Little, Proso (+ Foxtail). Kannada typing over ADB is not possible: Kannada search covered by automated/API tests only | Phone, API |
| 5 Crop health | **Passed** (3 public test photos through the phone's gallery, local `gemma3:4b`): spotted leaf -> "Most likely: Possible disease" 55%, signs "Dark spots, Yellowing" (81 s); tractor field -> "Unclear from this photo", "Photo: Not close up", tip "move closer…" (~90 s); healthy tomato -> "Most likely: Healthy" 65%. Every result shows "may be wrong" and the not-a-diagnosis disclaimer; "Checking the photo… up to a minute or two" with buttons disabled while waiting | Phone |
| 6a Demand withdrawal | **Passed**: validation "Choose a crop.", demand created (title "Browntop Millet · 10 kg", 0 notifications), Withdraw with Keep (no request) then confirm (200), "This demand was withdrawn", list shows Cancelled | Phone + DB |
| 6b Order notifications | **Passed end to end with test accounts**: order placed -> farmer bell "2", "New order #7E54E3D0: Browntop Millet"; Mark as read 2 -> 1 (persisted); farmer Accept -> Mark preparing -> Mark ready; buyer bell "3 unread": confirmed / preparing / ready with order id, crop, kg and status; Mark all read -> "All read", bell cleared; buyer order shows "Farm progress: Ready"; order cancelled (farmer notified) | Phone + DB |
| 7 Existing functions / logs | Sign-in with labelled development OTP, guided tour for a new buyer (Next/Back/Finish, recorded; not shown again on next sign-in), home weather, Harvest lot "Browntop Millet · PHONE-TEST plot, Stage3 Test Farm", plot create/delete, crop delete -> "Keep the history" -> Mark abandoned, plot delete -> Archive, assistant mixed question (29 s; record part "Measured", AI part labelled). Logcat: **no Harvestique crash**; the only crash in the log is `com.oneplus.note`; one Flutter error (bug 2) before the fix, none after | Phone |
| Rate limit | Repeated sign-ins hit "Too many codes were requested. Please try again in an hour." (5 per number per hour) | API |

## Not tested / needs you
* **Press-and-hold voice with real speech** (and Kannada speech): holding the mic records the room and sends it to the
  server, so it was not done without you. The short-tap hint was verified. Steps: Ask > hold the mic, say "How much
  did I spend this month?", release; hold again and slide away to cancel.
* Camera capture for crop health (gallery only was tested).
* Hub operations (batch, quality check, fulfilment) - admin flows, not run on the phone.
* Your real accounts were not used for anything.

## Test data left (history kept by design, test accounts only)
Abandoned crop "Browntop Millet" and archived "PHONE-TEST plot" on Stage3 Test Farm; cancelled order #7E54E3D0 with its
pool and participation; withdrawn demand; 3 crop-health results (hashes only); notifications of the two test accounts;
test buyer account. Nothing was deleted from real accounts.

## Automated results after the fixes
Backend: **1480 passed**, ruff/format/mypy clean. Flutter: **143 passed**, `flutter analyze` clean.
APK installed: `frontend/build/app/outputs/flutter-apk/app-debug.apk` (sha256 e8ccb7ed…26ef3), built with
`API_BASE_URL=http://192.168.29.100:8000/api/v1`.

## Next steps
1. Give the PC a fixed address so the app keeps working after restarts: a DHCP reservation for this PC (192.168.29.100)
   in the Wi-Fi router settings (your choice; not changed automatically). Otherwise the APK must be rebuilt whenever
   the address changes.
2. Try voice (steps above) and camera photos yourself.
3. Re-check on the phone: pull down to refresh a list; accept an order and then open Harvest (should show it at once).
4. Decide whether the test accounts and their data should be kept or removed (needs your approval).
