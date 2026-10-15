"""Reproducible accuracy evaluation of the configured crop-health classifier on labelled photos.

    python -m app.cli.eval_crop_health <images_dir> [--out report.json] [--per-class N --sample-seed S]
        [--reference-dir DIR] [--drop-duplicates] [--healthy-pattern REGEX] [--dataset-note TEXT]

<images_dir> has one folder per class (PlantDoc layout, e.g. "Tomato leaf", "Tomato Septoria leaf spot"). A folder is
ground truth "healthy" when its name matches --healthy-pattern (default: "<crop> leaf" with no disease words), else
"problem". The classifier is the one configured for the server (CROP_HEALTH_CLASSIFIER), called through the same
validation as the API (decode_image), one photo at a time.

What is measured (and only what was actually run):
* answered: the photo got a health label; "unknown" counts as a refusal, reported as coverage, not as an error;
* on answered photos: precision / recall / F1 for "healthy" and "problem" (possible disease, stress or deficiency
  all count as "problem": the classifier does not name diseases), macro F1, accuracy;
* the full confusion matrix (truth x returned label, including unknown), mean / p90 latency.
Disease-level top-3 accuracy is not applicable: by design the classifier gives categories, not disease names.
Duplicates and leakage: exact (SHA-256 of the bytes) and near duplicates (64-bit difference hash, Hamming distance
<= 6) are reported within the evaluated photos and against --reference-dir (e.g. the photos used to tune prompts and
thresholds); --drop-duplicates removes them before running. Harvestique did not train the model; whether the photos
were in the base model's own (web) training data cannot be checked from here and is reported as a limitation.
Progress is saved after every photo (<out>.partial.jsonl), and a re-run resumes where it stopped. A lock file
(<out>.lock, refreshed after every photo) stops a second run from writing the same checkpoint; a lock older than
LOCK_STALE_SECONDS is treated as left behind by a crash. --max-photos N stops after N new photos (small batches).

--rescore-only <checkpoint.jsonl> computes the metrics from saved answers without running the model, both as
answered and under CANDIDATE RULE "generic-spots-low" (pre-registered 2026-10-14 after the first 33 photos, before the
remaining photos were evaluated): a problem answer whose only described sign is generic "spots" (not brown/dark spots,
no other sign) with low model confidence is scored as "unknown". The rule is NOT used by the production pipeline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.enums import CropHealthClass
from app.providers.vision.base import CropHealthClassifier

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
LOCK_STALE_SECONDS = 15 * 60  # one photo takes ~1-2 min; a lock untouched this long was left by a crashed run
FIRST_33_PREREGISTERED = 33  # the candidate rule was chosen from the first 33 saved photos only
DEFAULT_HEALTHY = r"^[A-Za-z_ ]+ leaf$"  # PlantDoc: "Apple leaf", "Bell_pepper leaf", "grape leaf"
# Own photo sets (e.g. Karnataka): healthy folders END in " healthy" ("Ragi healthy"); every other folder is a problem.
# Safer than the PlantDoc default, which would call "Ragi blast leaf" healthy (no listed disease word).
EXPLICIT_HEALTHY = r"^[A-Za-z_ ]+ healthy$"
APP_MAX_SIDE, APP_JPEG_QUALITY = (
    1600,
    85,
)  # what the phone app does before upload (image_picker maxWidth/Height, quality)
DISEASE_WORDS = re.compile(r"spot|blight|rust|scab|mold|mould|mildew|virus|mosaic|rot|curl", re.IGNORECASE)
PROBLEM_LABELS = {CropHealthClass.POSSIBLE_DISEASE, CropHealthClass.STRESS, CropHealthClass.POSSIBLE_DEFICIENCY}


@dataclass
class Sample:
    path: Path
    folder: str
    truth: str  # "healthy" | "problem"


@dataclass
class Result:
    sample: Sample
    label: str
    seconds: float
    flags: list[str] = field(default_factory=list)
    error: str | None = None
    features: dict[str, Any] = field(default_factory=dict)


def truth_of(folder: str, healthy_pattern: str) -> str:
    if re.match(healthy_pattern, folder.strip()) and not DISEASE_WORDS.search(folder):
        return "healthy"
    return "problem"


def collect(images_dir: Path, healthy_pattern: str, limit_per_class: int | None) -> list[Sample]:
    samples: list[Sample] = []
    for folder in sorted(p for p in images_dir.iterdir() if p.is_dir()):
        files = sorted(f for f in folder.iterdir() if f.suffix.lower() in IMAGE_SUFFIXES)
        for f in files[:limit_per_class] if limit_per_class else files:
            samples.append(Sample(f, folder.name, truth_of(folder.name, healthy_pattern)))
    return samples


def sample_per_class(samples: list[Sample], per_class: int, seed: str) -> list[Sample]:
    """A reproducible stratified sample: in each folder, files ordered by SHA-256(seed + name), first N kept."""
    by_folder: dict[str, list[Sample]] = {}
    for s in samples:
        by_folder.setdefault(s.folder, []).append(s)
    out: list[Sample] = []
    for folder in sorted(by_folder):
        ranked = sorted(
            by_folder[folder], key=lambda s: hashlib.sha256(f"{seed}:{folder}/{s.path.name}".encode()).hexdigest()
        )
        out.extend(ranked[:per_class])
    return out


def dhash(path: Path) -> int | None:
    """64-bit difference hash: survives resizing and recompression, so near-identical copies match. None when the file
    cannot be read as an image (reported by the photo check, not a reason to stop)."""
    import numpy as np
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(path) as img:
            px = np.asarray(img.convert("L").resize((9, 8)), dtype=np.int16).ravel().tolist()
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | int(px[row * 9 + col] > px[row * 9 + col + 1])
    return bits


def duplicates(paths: list[Path], reference: list[Path], max_distance: int = 6) -> dict[str, Any]:
    """Exact and near-duplicate groups among `paths`, and members of `paths` that match a reference photo."""
    sha = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths + reference}
    dh = {p: dhash(p) for p in paths + reference}

    def is_near(a: Path, b: Path) -> bool:
        ha, hb = dh[a], dh[b]
        return ha is not None and hb is not None and bin(ha ^ hb).count("1") <= max_distance

    exact: dict[str, list[str]] = {}
    for p in paths:
        exact.setdefault(sha[p], []).append(f"{p.parent.name}/{p.name}")
    near = []
    for i, a in enumerate(paths):
        for b in paths[i + 1 :]:
            if sha[a] != sha[b] and is_near(a, b):
                near.append([f"{a.parent.name}/{a.name}", f"{b.parent.name}/{b.name}"])
    ref_hits = [
        [f"{p.parent.name}/{p.name}", r.name] for p in paths for r in reference if sha[p] == sha[r] or is_near(p, r)
    ]
    return {
        "exact_groups": [g for g in exact.values() if len(g) > 1],
        "near_pairs": near,
        "matches_reference": ref_hits,
        "max_hamming_distance": max_distance,
    }


def drop_duplicates(samples: list[Sample], dup: dict[str, Any]) -> list[Sample]:
    """Keep the first photo of each exact or near group; drop any photo that matches a reference (tuning) photo."""
    drop = {f for g in dup["exact_groups"] for f in g[1:]} | {b for _, b in dup["near_pairs"]}
    drop |= {p for p, _ in dup["matches_reference"]}
    return [s for s in samples if f"{s.folder}/{s.path.name}" not in drop]


def candidate_label(row: dict[str, Any]) -> str:
    """Label under the pre-registered rule "generic-spots-low" (evaluation only, not production)."""
    f = row.get("features") or {}
    if (
        row["label"] in {c.value for c in PROBLEM_LABELS}
        and list(f.get("symptoms") or []) == ["spots"]
        and f.get("ai_confidence") == "low"
    ):
        return CropHealthClass.UNKNOWN.value
    return str(row["label"])


def rows_to_results(rows: list[dict[str, Any]], *, rule: bool = False) -> list[Result]:
    out = []
    for r in rows:
        folder = r["file"].split("/")[0]
        label = candidate_label(r) if rule and r["error"] is None else r["label"]
        out.append(Result(Sample(Path(r["file"]), folder, r["truth"]), label, r["seconds"], r["flags"], r["error"]))
    return out


def load_checkpoint(path: Path) -> list[dict[str, Any]]:
    """Saved rows, last answer per photo (a retried error is replaced by its retry)."""
    latest: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            latest[row["file"]] = row
    return list(latest.values())


def rescore(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Metrics as answered and under the candidate rule, overall and on the photos the rule was NOT chosen from."""
    held_out = rows[FIRST_33_PREREGISTERED:]
    return {
        "photos_in_checkpoint": len(rows),
        "as_answered": metrics(rows_to_results(rows)),
        "candidate_rule_generic_spots_low": metrics(rows_to_results(rows, rule=True)),
        "held_out_after_rule_was_fixed": {
            "photos": len(held_out),
            "as_answered": metrics(rows_to_results(held_out)) if held_out else None,
            "candidate_rule": metrics(rows_to_results(held_out, rule=True)) if held_out else None,
        },
        "note": "The candidate rule is evaluation-only; production behaviour is unchanged.",
    }


class LockedError(RuntimeError):
    pass


def acquire_lock(lock: Path) -> None:
    if lock.exists() and time.time() - lock.stat().st_mtime < LOCK_STALE_SECONDS:
        raise LockedError(f"another evaluation is using this checkpoint ({lock}); not starting a second one")
    lock.write_text(f"{time.time()}\n", encoding="utf-8")


def photo_bytes(path: Path, app_resize: bool) -> bytes:
    """The bytes the server would receive. With app_resize, shrink to <= 1600 px and re-encode as JPEG quality 85,
    like the phone app does before upload (raw 50 MP phone photos exceed the server's 5 MB / 25 MP limits)."""
    data = path.read_bytes()
    if not app_resize:
        return data
    import io

    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = 200_000_000  # phone originals only; the server's own limits apply afterwards
    with Image.open(io.BytesIO(data)) as original:
        img = ImageOps.exif_transpose(original).convert("RGB")
        img.thumbnail((APP_MAX_SIDE, APP_MAX_SIDE))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=APP_JPEG_QUALITY)
    return buf.getvalue()


def check_photos(samples: list[Sample], app_resize: bool, dup: dict[str, Any]) -> dict[str, Any]:
    """Validate every photo exactly as a run would (preparation + server decode), without calling any model."""
    from app.services.media import decode_image

    problems = []
    by_folder: dict[str, dict[str, Any]] = {}
    for s in samples:
        entry = by_folder.setdefault(s.folder, {"truth": s.truth, "photos": 0, "unusable": 0})
        entry["photos"] += 1
        try:
            decode_image(photo_bytes(s.path, app_resize))
        except Exception as exc:  # report every unusable file with the reason a run would hit
            entry["unusable"] += 1
            problems.append({"file": _key(s), "reason": getattr(exc, "code", type(exc).__name__)})
    truths = Counter(s.truth for s in samples)
    return {
        "photos": len(samples),
        "healthy": truths.get("healthy", 0),
        "problem": truths.get("problem", 0),
        "folders": by_folder,
        "unusable_photos": problems,
        "exact_duplicate_groups": dup["exact_groups"],
        "near_duplicate_pairs": dup["near_pairs"],
        "matches_reference_photos": dup["matches_reference"],
        "app_resize": app_resize,
    }


def predicted_group(label: str) -> str | None:
    """'healthy', 'problem' or None (no answer)."""
    if label == CropHealthClass.HEALTHY.value:
        return "healthy"
    if label in {c.value for c in PROBLEM_LABELS}:
        return "problem"
    return None


def metrics(results: list[Result]) -> dict[str, Any]:
    ran = [r for r in results if r.error is None]
    answered = [(r.sample.truth, g) for r in ran if (g := predicted_group(r.label)) is not None]
    per_class: dict[str, dict[str, float | int]] = {}
    for cls in ("healthy", "problem"):
        tp = sum(1 for t, p in answered if t == cls and p == cls)
        fp = sum(1 for t, p in answered if t != cls and p == cls)
        fn = sum(1 for t, p in answered if t == cls and p != cls)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        support = sum(1 for t, _ in answered if t == cls)
        per_class[cls] = {
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "support_answered": support,
        }
    confusion: dict[str, dict[str, int]] = {}
    for r in ran:
        confusion.setdefault(r.sample.truth, Counter())[r.label] += 1
    per_folder: dict[str, dict[str, int]] = {}
    for r in ran:
        per_folder.setdefault(r.sample.folder, Counter())[r.label] += 1
    seconds = sorted(r.seconds for r in ran)
    by_truth = Counter(r.sample.truth for r in ran)
    unclear_by_truth = Counter(r.sample.truth for r in ran if predicted_group(r.label) is None)
    return {
        "photos": len(results),
        "errors": len(results) - len(ran),
        "answered": len(answered),
        "coverage": round(len(answered) / len(ran), 3) if ran else 0.0,
        "unclear_rate_by_truth": {k: round(unclear_by_truth[k] / v, 3) for k, v in by_truth.items()},
        "accuracy_on_answered": round(sum(1 for t, p in answered if t == p) / len(answered), 3) if answered else None,
        "per_class": per_class,
        "macro_f1_on_answered": round(statistics.mean(c["f1"] for c in per_class.values()), 3) if answered else None,
        "confusion_truth_x_label": {k: dict(v) for k, v in confusion.items()},
        "labels_by_source_class": {k: dict(v) for k, v in sorted(per_folder.items())},
        "flags": dict(Counter(f for r in ran for f in r.flags)),
        "latency_seconds": {
            "mean": round(statistics.mean(seconds), 1) if seconds else None,
            "p90": round(seconds[min(len(seconds) - 1, int(0.9 * len(seconds)))], 1) if seconds else None,
        },
        "top3_disease_accuracy": "not applicable: the classifier returns categories, not disease names",
    }


def _key(s: Sample) -> str:
    return f"{s.folder}/{s.path.name}"


def run(
    classifier: CropHealthClassifier,
    samples: list[Sample],
    language: str = "en",
    progress: Path | None = None,
    max_new: int | None = None,
    lock: Path | None = None,
    app_resize: bool = False,
) -> list[Result]:
    from app.services.media import decode_image

    done: dict[str, dict[str, Any]] = {}
    if progress is not None and progress.exists():
        for line in progress.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                done[row["file"]] = row
    results = []
    new = 0
    for i, s in enumerate(samples, 1):
        if _key(s) in done and done[_key(s)]["error"] is None:  # resumed run: reuse saved answers, retry errors
            row = done[_key(s)]
            results.append(Result(s, row["label"], row["seconds"], row["flags"], row["error"], row.get("features", {})))
            continue
        if max_new is not None and new >= max_new:
            break  # batch finished; the next run continues from the checkpoint
        new += 1
        t = time.perf_counter()
        try:
            a = classifier.assess(decode_image(photo_bytes(s.path, app_resize)), language)
            keep = {k: v for k, v in a.features.items() if k in KEPT_FEATURES}
            # the model did not answer (timeout, not loaded...) and the colour check stood in: that is not the model's
            # judgement, so it is an error for this evaluation, never an "unclear" answer
            error = "model_unavailable_fallback" if a.features.get("ai_unavailable") else None
            results.append(Result(s, a.label.value, time.perf_counter() - t, list(a.quality_flags), error, keep))
        except Exception as exc:  # one bad file must not stop the evaluation; it is counted as an error
            results.append(Result(s, "error", time.perf_counter() - t, error=type(exc).__name__))
        r = results[-1]
        if progress is not None:
            with progress.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(_row(r)) + "\n")
        if lock is not None:
            lock.touch()  # heartbeat: a live run keeps its lock fresh
        print(f"[{i}/{len(samples)}] {s.folder} -> {r.label} ({r.seconds:.0f}s)", flush=True)
    return results


KEPT_FEATURES = (
    "symptoms",
    "ai_overall",
    "ai_confidence",
    "ai_description",
    "precheck",
    "mode",
    "crop_seen",
    "plant_part",
)


def _row(r: Result) -> dict[str, Any]:
    return {
        "file": _key(r.sample),
        "truth": r.sample.truth,
        "label": r.label,
        "seconds": round(r.seconds, 1),
        "flags": r.flags,
        "error": r.error,
        "features": r.features,
    }


def provenance(samples: list[Sample]) -> str:
    h = hashlib.sha256()
    for s in samples:
        h.update(f"{s.folder}/{s.path.name}\n".encode())
    return h.hexdigest()


def main(argv: list[str] | None = None, classifier: CropHealthClassifier | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("images_dir", type=Path)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--limit-per-class", type=int, default=None, help="first N files per folder, by name")
    p.add_argument("--per-class", type=int, default=None, help="reproducible stratified sample of N per folder")
    p.add_argument("--sample-seed", default="harvestique-eval-1")
    p.add_argument("--reference-dir", type=Path, default=None, help="photos used for tuning: must not be evaluated")
    p.add_argument("--drop-duplicates", action="store_true")
    p.add_argument("--max-photos", type=int, default=None, help="stop after N new photos (resume later)")
    p.add_argument("--rescore-only", type=Path, default=None, help="metrics from a saved checkpoint, no model calls")
    p.add_argument("--app-resize", action="store_true", help="prepare photos like the phone app (<=1600 px, JPEG 85)")
    p.add_argument("--check-only", action="store_true", help="validate photos, labels and duplicates; no model")
    p.add_argument("--healthy-pattern", default=DEFAULT_HEALTHY)
    p.add_argument("--dataset-note", default="", help="where the photos came from and their licence")
    args = p.parse_args(argv)
    if args.rescore_only is not None:
        report = rescore(load_checkpoint(args.rescore_only))
        text = json.dumps(report, indent=2)
        if args.out:
            args.out.write_text(text, encoding="utf-8")
        print(text)
        return 0
    if classifier is None:
        from app.core.config import get_settings
        from app.providers.registry import build_crop_health_classifier

        classifier = build_crop_health_classifier(get_settings())
    everything = collect(args.images_dir, args.healthy_pattern, args.limit_per_class)
    if not everything:
        print("No images found.", file=sys.stderr)
        return 2
    reference = (
        sorted(f for f in args.reference_dir.rglob("*") if f.is_file() and f.suffix.lower() in IMAGE_SUFFIXES)
        if args.reference_dir
        else []
    )
    dup = duplicates([s.path for s in everything], reference)  # checked over the whole folder set, not just the sample
    if args.check_only:
        print(json.dumps(check_photos(everything, args.app_resize, dup), indent=2))
        return 0
    pool = drop_duplicates(everything, dup) if args.drop_duplicates else everything
    samples = sample_per_class(pool, args.per_class, args.sample_seed) if args.per_class else pool
    progress = args.out.with_suffix(".partial.jsonl") if args.out else None
    lock = args.out.with_suffix(".lock") if args.out else None
    if lock is not None:
        try:
            acquire_lock(lock)
        except LockedError as exc:
            print(str(exc), file=sys.stderr)
            return 3
    try:
        results = run(
            classifier, samples, progress=progress, max_new=args.max_photos, lock=lock, app_resize=args.app_resize
        )
    finally:
        if lock is not None:
            lock.unlink(missing_ok=True)
    if len(results) < len(samples):  # a batch: keep the checkpoint, write no final report yet
        print(f"Batch done: {len(results)}/{len(samples)} photos answered so far; run again to continue.")
        return 0
    wrong = [
        _row(r)
        for r in results
        if r.error is None and (g := predicted_group(r.label)) is not None and g != r.sample.truth
    ]
    report = {
        "classifier": f"{classifier.name} {classifier.version}",
        # full model name (the stored version is cut to 16 characters, e.g. "granite3.2-visio")
        "model": os.environ.get("OLLAMA_VISION_MODEL", ""),
        "dataset_note": args.dataset_note,
        "selection": {
            "photos_found": len(everything),
            "after_duplicate_removal": len(pool),
            "evaluated": len(samples),
            "per_class": args.per_class,
            "sample_seed": args.sample_seed,
            "healthy_pattern": args.healthy_pattern,
        },
        "duplicates": dup,
        "file_list_sha256": provenance(samples),
        "metrics": metrics(results),
        "wrong_answers": wrong,
        "per_photo": [_row(r) for r in results],
    }
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
