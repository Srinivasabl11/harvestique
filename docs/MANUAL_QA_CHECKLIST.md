# Manual QA checklist (works without any AI tool)

Use before installing a new build on the phone. Every step uses software already on this PC.

## 1. Automatic checks (PowerShell, from the project folder)
```powershell
cd C:\Users\Srinivasa\Documents\harvestique
powershell -ExecutionPolicy Bypass -File scripts\test-backend.ps1        # lint, format, types, all backend tests (~15 min)
powershell -ExecutionPolicy Bypass -File scripts\validate.ps1            # the above + docker compose config + Flutter analyze/test
cd frontend; flutter analyze; flutter test                                # app only
```
All must end without failures. The tests use their own database (`harvestique_test`); live data is not touched.

## 2. Back up before anything that changes the database
```powershell
docker exec harvestique-db-1 pg_dump -U harvestique -d harvestique -Fc -f /tmp/backup.dump
docker cp harvestique-db-1:/tmp/backup.dump C:\Users\Srinivasa\Documents\harvestique-backups\harvestique_<date>.dump
```
Keep the file; restore with `pg_restore` into a scratch database to prove it is usable.

## 3. Build and install (data kept)
```powershell
ipconfig   # note the Wi-Fi IPv4 address of this PC, e.g. 192.168.29.100
cd frontend
flutter build apk --debug --dart-define=API_BASE_URL=http://<PC address>:8000/api/v1
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" install -r build\app\outputs\flutter-apk\app-debug.apk
```
Never uninstall the app (that deletes its data). `install -r` keeps it.

## 4. Phone checks (use a test account, not real farmers)
| Area | Do | Expect |
|---|---|---|
| Sign-in | Sign in, enter the code | Code screen says DEVELOPMENT MODE on a dev server |
| Home | Look at Weather | Starts with "Today"; "Updated hh:mm"; rain chance per hour |
| Refresh | Pull a list down | It reloads (spinner, then fresh data) |
| My Farm | Add plot, add crop (try a category chip), field work log add / edit / delete | Saved; delete asks first |
| Crop health | Gallery photo of a leaf; a very blurred photo | Leaf: result in 1-2 min with "may be wrong"; blurred: instant "Unclear" with a retake tip |
| Market (farmer) | Accept a request, Mark preparing, Mark ready | Buyer bell shows each step |
| Orders (buyer) | Open an order, Cancel order | Confirmation first |
| Notifications | Mark one read, Mark all read | Count drops; bell label updates |
| Assistant | Type a question; hold the mic and speak | Answer with record part and labelled AI part |

## 5. Before a release
* Read the server log for errors: `docker logs --since 30m harvestique-backend-1`
* Check the phone log for app crashes:
  `adb logcat -d | Select-String "FATAL EXCEPTION|E flutter"`
