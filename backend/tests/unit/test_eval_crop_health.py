"""The crop-health evaluation harness: folder ground truth, metrics arithmetic, errors counted, no fabrication."""

from __future__ import annotations

import json

import numpy as np
from PIL import Image

from app.cli.eval_crop_health import collect, main, metrics, truth_of
from app.core.enums import CropHealthClass as C
from app.domain.vision import HealthAssessment


def test_folder_names_give_ground_truth():
    assert truth_of("Tomato leaf", r"^[A-Za-z_ ]+ leaf$") == "healthy"
    assert truth_of("Bell_pepper leaf", r"^[A-Za-z_ ]+ leaf$") == "healthy"
    assert truth_of("Tomato Septoria leaf spot", r"^[A-Za-z_ ]+ leaf$") == "problem"
    assert truth_of("Corn rust leaf", r"^[A-Za-z_ ]+ leaf$") == "problem"  # disease word wins
    assert truth_of("Squash Powdery mildew leaf", r"^[A-Za-z_ ]+ leaf$") == "problem"


class _Scripted:
    """Answers by folder: lets the metrics be checked by hand."""

    name, version = "scripted", "1"

    def __init__(self, answers):
        self.answers = answers
        self.i = 0

    def assess(self, rgb, language):
        label = self.answers[self.i]
        self.i += 1
        if label == "boom":
            raise RuntimeError("model crashed")
        return HealthAssessment(C(label), {}, {}, [], "", "")


def _photos(tmp_path, folders):
    rng = np.random.default_rng(0)
    for folder, n in folders.items():
        (tmp_path / folder).mkdir()
        for i in range(n):
            a = np.clip(np.full((96, 96, 3), (60, 140, 50)) + rng.normal(0, 25, (96, 96, 3)), 0, 255).astype(np.uint8)
            Image.fromarray(a).save(tmp_path / folder / f"{i}.jpg")
    return tmp_path


def test_metrics_are_computed_from_what_was_run(tmp_path, capsys):
    images = _photos(tmp_path, {"Tomato leaf": 2, "Tomato Early blight leaf": 3})
    # sorted folders: "Tomato Early blight leaf" (problem) first, then "Tomato leaf" (healthy)
    clf = _Scripted(["possible_disease", "stress", "unknown", "healthy", "boom"])
    out = tmp_path / "report.json"
    assert main([str(images), "--out", str(out)], classifier=clf) == 0
    report = json.loads(out.read_text())
    m = report["metrics"]
    assert m["photos"] == 5 and m["errors"] == 1 and m["answered"] == 3
    assert m["coverage"] == 0.75  # 3 answered of 4 that ran
    assert m["per_class"]["problem"] == {"precision": 1.0, "recall": 1.0, "f1": 1.0, "support_answered": 2}
    assert m["per_class"]["healthy"]["recall"] == 1.0
    assert m["confusion_truth_x_label"]["problem"] == {"possible_disease": 1, "stress": 1, "unknown": 1}
    assert m["top3_disease_accuracy"].startswith("not applicable")
    assert report["per_photo"][-1]["error"] == "RuntimeError"
    assert len(report["file_list_sha256"]) == 64


def test_an_all_unknown_run_reports_no_accuracy_instead_of_inventing_one():
    from app.cli.eval_crop_health import Result, Sample

    rs = [Result(Sample(None, "Tomato leaf", "healthy"), "unknown", 1.0)]  # type: ignore[arg-type]
    m = metrics(rs)
    assert m["answered"] == 0 and m["accuracy_on_answered"] is None and m["macro_f1_on_answered"] is None


def test_limit_per_class(tmp_path):
    images = _photos(tmp_path, {"Apple leaf": 4, "Apple rust leaf": 4})
    assert len(collect(images, r"^[A-Za-z_ ]+ leaf$", 2)) == 4


def test_stratified_sample_is_reproducible_and_seeded(tmp_path):
    from app.cli.eval_crop_health import sample_per_class

    images = _photos(tmp_path, {"Apple leaf": 6, "Apple rust leaf": 6})
    pool = collect(images, r"^[A-Za-z_ ]+ leaf$", None)
    a = sample_per_class(pool, 2, "seed-1")
    assert [s.path.name for s in a] == [s.path.name for s in sample_per_class(pool, 2, "seed-1")]
    assert len(a) == 4 and {s.folder for s in a} == {"Apple leaf", "Apple rust leaf"}
    other = sample_per_class(pool, 2, "seed-2")
    assert [s.path.name for s in other] != [s.path.name for s in a] or len(pool) <= 4


def test_duplicates_and_tuning_photos_are_found_and_dropped(tmp_path):
    from app.cli.eval_crop_health import drop_duplicates, duplicates

    root = tmp_path / "set"
    root.mkdir()
    images = _photos(root, {"Tomato leaf": 3, "Tomato Early blight leaf": 1})
    folder = images / "Tomato leaf"
    (folder / "copy.jpg").write_bytes((folder / "0.jpg").read_bytes())  # exact copy
    Image.open(folder / "1.jpg").resize((80, 80)).save(folder / "resized.jpg")  # near copy (resized)
    ref = tmp_path / "ref"
    ref.mkdir()
    (ref / "tuning.jpg").write_bytes((images / "Tomato Early blight leaf" / "0.jpg").read_bytes())
    pool = collect(images, r"^[A-Za-z_ ]+ leaf$", None)
    dup = duplicates([s.path for s in pool], sorted(ref.iterdir()))
    assert any(set(g) == {"Tomato leaf/0.jpg", "Tomato leaf/copy.jpg"} for g in dup["exact_groups"])
    assert any("Tomato leaf/resized.jpg" in pair for pair in dup["near_pairs"])
    assert dup["matches_reference"] == [["Tomato Early blight leaf/0.jpg", "tuning.jpg"]]
    kept = {f"{s.folder}/{s.path.name}" for s in drop_duplicates(pool, dup)}
    assert "Tomato Early blight leaf/0.jpg" not in kept  # a tuning photo is never evaluated
    assert len({"Tomato leaf/0.jpg", "Tomato leaf/copy.jpg"} & kept) == 1


def test_a_stopped_run_resumes_without_asking_the_model_again(tmp_path):
    (tmp_path / "set").mkdir()
    images = _photos(tmp_path / "set", {"Tomato leaf": 2})
    out = tmp_path / "report.json"
    first = _Scripted(["healthy", "boom"])
    main([str(images), "--out", str(out)], classifier=first)
    partial = out.with_suffix(".partial.jsonl")
    lines = partial.read_text().splitlines()
    assert len(lines) == 2
    partial.write_text(lines[0] + "\n")  # pretend it stopped after the first photo
    second = _Scripted(["stress"])
    main([str(images), "--out", str(out)], classifier=second)
    assert second.i == 1  # only the missing photo was sent to the model
    report = json.loads(out.read_text())
    assert [p["label"] for p in report["per_photo"]] == ["healthy", "stress"]
    assert report["wrong_answers"][0]["label"] == "stress"


def test_a_colour_fallback_is_an_error_not_an_unclear_answer_and_is_retried(tmp_path):
    (tmp_path / "set").mkdir()
    images = _photos(tmp_path / "set", {"Tomato leaf": 1})

    class _Fallback:
        name, version = "scripted", "1"

        def assess(self, rgb, language):
            return HealthAssessment(C.UNKNOWN, {}, {"ai_unavailable": True, "mode": "measurements_only"}, [], "", "")

    out = tmp_path / "report.json"
    main([str(images), "--out", str(out)], classifier=_Fallback())
    m = json.loads(out.read_text())["metrics"]
    assert m["errors"] == 1 and m["answered"] == 0 and m["unclear_rate_by_truth"] == {}
    again = _Scripted(["healthy"])
    main([str(images), "--out", str(out)], classifier=again)
    assert again.i == 1  # the failed photo was asked again on resume
    assert json.loads(out.read_text())["metrics"]["answered"] == 1


def _row(file, truth, label, symptoms, conf, error=None):
    return {
        "file": file,
        "truth": truth,
        "label": label,
        "seconds": 70.0,
        "flags": [],
        "error": error,
        "features": {"symptoms": symptoms, "ai_confidence": conf},
    }


def test_candidate_rule_only_touches_generic_spots_at_low_confidence():
    from app.cli.eval_crop_health import candidate_label

    assert candidate_label(_row("a/1.jpg", "healthy", "possible_disease", ["spots"], "low")) == "unknown"
    assert candidate_label(_row("a/2.jpg", "problem", "possible_disease", ["spots"], "medium")) == "possible_disease"
    assert (
        candidate_label(_row("a/3.jpg", "problem", "possible_disease", ["spots", "yellowing"], "low"))
        == "possible_disease"
    )
    assert candidate_label(_row("a/4.jpg", "problem", "possible_disease", ["dark_spots"], "low")) == "possible_disease"
    assert candidate_label(_row("a/5.jpg", "healthy", "healthy", [], "high")) == "healthy"


def test_rescore_only_needs_no_model_and_separates_held_out_photos(tmp_path):
    rows = [_row(f"Tomato leaf/{i}.jpg", "healthy", "possible_disease", ["spots"], "low") for i in range(33)]
    rows += [
        _row("Tomato leaf/late.jpg", "healthy", "possible_disease", ["spots"], "low"),
        _row("Tomato Early blight leaf/x.jpg", "problem", "possible_disease", ["brown_spots"], "medium"),
    ]
    ckpt = tmp_path / "c.partial.jsonl"
    ckpt.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    out = tmp_path / "rescore.json"
    assert main(["unused", "--rescore-only", str(ckpt), "--out", str(out)]) == 0
    rep = json.loads(out.read_text())
    assert rep["as_answered"]["answered"] == 35
    assert rep["candidate_rule_generic_spots_low"]["answered"] == 1  # 34 generic-spots-low answers become unknown
    held = rep["held_out_after_rule_was_fixed"]
    assert held["photos"] == 2 and held["candidate_rule"]["per_class"]["problem"]["recall"] == 1.0


def test_checkpoint_keeps_the_latest_answer_per_photo(tmp_path):
    from app.cli.eval_crop_health import load_checkpoint

    ckpt = tmp_path / "c.jsonl"
    ckpt.write_text(
        json.dumps(_row("a/1.jpg", "healthy", "error", [], None, error="Timeout"))
        + "\n"
        + json.dumps(_row("a/1.jpg", "healthy", "healthy", [], "high"))
        + "\n"
    )
    rows = load_checkpoint(ckpt)
    assert len(rows) == 1 and rows[0]["label"] == "healthy"


def test_a_second_run_on_the_same_checkpoint_is_refused_and_batches_stop_early(tmp_path):
    import os

    (tmp_path / "set").mkdir()
    images = _photos(tmp_path / "set", {"Tomato leaf": 3})
    out = tmp_path / "report.json"
    lock = out.with_suffix(".lock")
    lock.write_text("live")
    assert main([str(images), "--out", str(out)], classifier=_Scripted(["healthy"] * 3)) == 3  # refused
    os.utime(lock, (0, 0))  # a lock untouched for ages was left by a crash: allowed
    first = _Scripted(["healthy"] * 3)
    assert main([str(images), "--out", str(out), "--max-photos", "2"], classifier=first) == 0
    assert first.i == 2 and not out.exists() and not lock.exists()  # batch: checkpoint only, lock released
    rest = _Scripted(["healthy"])
    assert main([str(images), "--out", str(out)], classifier=rest) == 0
    assert rest.i == 1 and json.loads(out.read_text())["metrics"]["answered"] == 3


# ---------------------------------------------------------------- own photo sets (Karnataka)
def test_explicit_healthy_convention_never_calls_an_unlisted_disease_healthy():
    from app.cli.eval_crop_health import DEFAULT_HEALTHY, EXPLICIT_HEALTHY

    assert truth_of("Ragi blast leaf", DEFAULT_HEALTHY) == "healthy"  # the PlantDoc rule's blind spot
    assert truth_of("Ragi blast leaf", EXPLICIT_HEALTHY) == "problem"
    assert truth_of("Ragi healthy", EXPLICIT_HEALTHY) == "healthy"
    assert truth_of("Bell pepper healthy", EXPLICIT_HEALTHY) == "healthy"
    assert truth_of("Paddy blast", EXPLICIT_HEALTHY) == "problem"
    assert truth_of("Tomato leaf curl", EXPLICIT_HEALTHY) == "problem"


def test_app_resize_makes_big_phone_photos_usable_like_the_app_does(tmp_path):
    import pytest as _pt

    from app.cli.eval_crop_health import photo_bytes
    from app.core.errors import DomainValidationError
    from app.services.media import decode_image

    big = tmp_path / "phone.jpg"
    Image.fromarray(np.full((6000, 9000, 3), (60, 140, 50), dtype=np.uint8)).save(big, quality=95)
    with _pt.raises(DomainValidationError):
        decode_image(photo_bytes(big, app_resize=False))  # 9000 px side: over the server limit
    rgb = decode_image(photo_bytes(big, app_resize=True))
    assert max(rgb.shape[:2]) <= 1600


def test_check_only_reports_labels_unusable_files_and_duplicates_without_a_model(tmp_path, capsys):
    root = tmp_path / "karnataka"
    root.mkdir()
    images = _photos(root, {"Ragi healthy": 2, "Ragi blast": 2})
    (images / "Ragi blast" / "broken.jpg").write_bytes(b"not an image")
    ref = tmp_path / "plantdoc" / "Some class"
    ref.mkdir(parents=True)
    (ref / "same.jpg").write_bytes((images / "Ragi healthy" / "0.jpg").read_bytes())

    class _NoModel:
        name, version = "none", "0"

        def assess(self, rgb, language):
            raise AssertionError("check-only must not call the model")

    rc = main(
        [
            str(images),
            "--check-only",
            "--healthy-pattern",
            r"^[A-Za-z_ ]+ healthy$",
            "--reference-dir",
            str(tmp_path / "plantdoc"),
            "--app-resize",
        ],
        classifier=_NoModel(),
    )
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["healthy"] == 2 and report["problem"] == 3
    assert report["folders"]["Ragi blast"]["unusable"] == 1
    assert report["unusable_photos"][0]["file"] == "Ragi blast/broken.jpg"
    assert report["matches_reference_photos"] == [["Ragi healthy/0.jpg", "same.jpg"]]
