# Runs (or continues) a crop-health evaluation in small, resumable batches through the local Ollama, with the same
# pipeline as the server. Does not touch the live database or server, and never changes the server's settings.
#
#   powershell -ExecutionPolicy Bypass -File scripts\eval-plantdoc.ps1                 # PlantDoc, gemma3:4b, 15 photos per batch
#   powershell -ExecutionPolicy Bypass -File scripts\eval-plantdoc.ps1 -RescoreOnly    # metrics from saved answers, no model
#   powershell -ExecutionPolicy Bypass -File scripts\eval-plantdoc.ps1 -Model granite3.2-vision:2b   # another (installed) model
#   powershell -ExecutionPolicy Bypass -File scripts\eval-plantdoc.ps1 -ImagesSubdir karnataka -PerClass 0 -Name karnataka_gemma3_4b
#
# Each model/dataset gets its own checkpoint, lock and report under <Data>\results\<Name>.*, so runs never mix.
# Photo folders go under <Data> with one sub-folder per class ("Ragi leaf" = healthy, "Ragi blast leaf" = problem).
# It refuses to start when another evaluation is running or when memory is too tight (running the model with too
# little memory froze Docker on 2026-10-14). Completed photos are never sent to the model again.
param(
    [int]$Batch = 15,
    [switch]$RescoreOnly,
    [string]$Model = "gemma3:4b",
    [string]$ImagesSubdir = "plantdoc_test",
    [int]$PerClass = 4,                  # 0 = every photo
    [string]$Name = "",                  # default: plantdoc_<model>_108 (the existing PlantDoc run)
    [string]$Data = "C:\Users\Srinivasa\Documents\harvestique-eval-data",
    [int]$MaxCommitPercent = 75,
    [int]$MinAvailableMB = 1500,
    [switch]$DryRun,                     # show the files and checks a run would use; run nothing
    [int]$MaxBatches = 0,                # stop after N batches (0 = run to the end), e.g. a 1-batch pilot
    [string]$HealthyPattern = "",        # own photo sets: '^[A-Za-z_ ]+ healthy$' (folders ending in " healthy")
    [switch]$AppResize,                  # own phone photos: shrink like the app does before upload (<=1600 px, JPEG 85)
    [string]$ReferenceSubdir = "",       # photos that must not appear in the set (e.g. plantdoc_test), checked for duplicates
    [ValidateSet("v1", "v2")][string]$PromptVersion = "v1"   # CROP_HEALTH_PROMPT_VERSION for this run only
)
# native tools (docker, ollama) write progress to stderr; Windows PowerShell 5.1 would treat that as a fatal error
# under "Stop", so failures are detected from exit codes instead
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
if (-not $Name) { $Name = "plantdoc_" + ($Model -replace '[:./]', '_') + "_108" }
$out = "/data/results/$Name.json"
$checkpoint = "/data/results/$Name.partial.jsonl"
$common = @("-v", "${root}\backend:/src/backend:ro", "-v", "${Data}:/data", "-e", "PYTHONDONTWRITEBYTECODE=1")
$image = @("--entrypoint", "sh", "hq-test-runner")  # must come after every docker option

if ($RescoreOnly) {
    docker run --rm @common @image -c "cd /src/backend && PYTHONPATH=/src/backend python -m app.cli.eval_crop_health unused --rescore-only $checkpoint --out /data/results/${Name}_rescore.json"
    exit $LASTEXITCODE
}

$extra = ""
if ($HealthyPattern) { $extra += " --healthy-pattern '$HealthyPattern'" }
if ($AppResize) { $extra += " --app-resize" }
if ($ReferenceSubdir) { $extra += " --reference-dir /data/$ReferenceSubdir" }
$installed = (ollama list 2>$null) -join "`n"
$isInstalled = $installed -match [regex]::Escape($Model)
if ($DryRun) {
    $c = (Get-Counter '\Memory\Committed Bytes', '\Memory\Commit Limit', '\Memory\Available MBytes').CounterSamples
    Write-Host "Run name:     $Name"
    Write-Host "Model:        $Model (installed: $isInstalled), prompt $PromptVersion"
    Write-Host "Photos:       $Data\$ImagesSubdir (exists: $(Test-Path (Join-Path $Data $ImagesSubdir))), per class: $PerClass"
    Write-Host "Checkpoint:   $Data\results\$Name.partial.jsonl (exists: $(Test-Path (Join-Path $Data "results\$Name.partial.jsonl")))"
    Write-Host "Report:       $Data\results\$Name.json (exists: $(Test-Path (Join-Path $Data "results\$Name.json")))"
    Write-Host "Lock:         $Data\results\$Name.lock (exists: $(Test-Path (Join-Path $Data "results\$Name.lock")))"
    Write-Host ("Memory now:   committed {0}% of the limit, {1} MB available (needs <= {2}% and >= {3} MB)" -f [int](100 * $c[0].CookedValue / $c[1].CookedValue), [int]$c[2].CookedValue, $MaxCommitPercent, $MinAvailableMB)
    Write-Host "Running evaluation containers: $(docker ps --filter 'name=hq-eval' --format '{{.Names}}')"
    if (Test-Path (Join-Path $Data $ImagesSubdir)) {
        # validate every photo, label and duplicate exactly as a run would, without loading any model
        Write-Host "Photo check (no model):"
        docker run --rm @common @image -c "cd /src/backend && PYTHONPATH=/src/backend python -m app.cli.eval_crop_health /data/$ImagesSubdir --check-only $extra"
    }
    exit 0
}
if (-not (Test-Path (Join-Path $Data $ImagesSubdir))) { Write-Host "No photo folder $Data\$ImagesSubdir" -ForegroundColor Red; exit 2 }
if (-not $isInstalled) {
    Write-Host "Model $Model is not installed in Ollama (nothing is downloaded automatically)." -ForegroundColor Red; exit 2
}
$running = docker ps --filter "name=hq-eval" --format "{{.Names}}"
if ($running) { Write-Host "An evaluation is already running ($running). Not starting another." -ForegroundColor Yellow; exit 3 }

$sampling = if ($PerClass -gt 0) { "--per-class $PerClass --sample-seed harvestique-eval-1" } else { "" }
# The Ollama process serving a vision model grows with every photo (gemma3:4b: 4 GB -> 9 GB over ~35 photos on
# 2026-10-14), so the model is unloaded after each batch: the next photo reloads it fresh and memory returns to normal.
$final = Join-Path $Data "results\$Name.json"
$batches = 0
while (-not (Test-Path $final)) {
    if ($MaxBatches -gt 0 -and $batches -ge $MaxBatches) { Write-Host "Stopped after $batches batch(es) as asked; run again to continue." -ForegroundColor Green; exit 0 }
    $batches++
    $c = (Get-Counter '\Memory\Committed Bytes', '\Memory\Commit Limit', '\Memory\Available MBytes').CounterSamples
    $commit = [int](100 * $c[0].CookedValue / $c[1].CookedValue); $avail = [int]$c[2].CookedValue
    Write-Host "Memory: committed $commit% of the limit, $avail MB available"
    if ($commit -gt $MaxCommitPercent -or $avail -lt $MinAvailableMB) {
        Write-Host "Not enough memory to load the model safely (need commit <= $MaxCommitPercent% and >= $MinAvailableMB MB available)." -ForegroundColor Yellow
        Write-Host "Close large programs (browsers, desktop chat apps, unneeded containers) and run this again." -ForegroundColor Yellow
        exit 4
    }
    docker run --rm --name hq-eval-batch @common `
        -e CROP_HEALTH_CLASSIFIER=ollama_vision -e OLLAMA_BASE_URL=http://host.docker.internal:11434 `
        -e OLLAMA_VISION_MODEL=$Model -e VISION_TIMEOUT_SECONDS=150 -e CROP_HEALTH_PROMPT_VERSION=$PromptVersion @image `
        -c "cd /src/backend && PYTHONPATH=/src/backend python -m app.cli.eval_crop_health /data/$ImagesSubdir $sampling $extra --drop-duplicates --max-photos $Batch --out $out --dataset-note '$ImagesSubdir'"
    $code = $LASTEXITCODE
    ollama stop $Model *> $null   # release the grown model process
    if ($code -ne 0) { Write-Host "Batch failed (exit $code); the checkpoint is kept." -ForegroundColor Red; exit $code }
}
Write-Host "Evaluation complete: $final" -ForegroundColor Green
exit 0
