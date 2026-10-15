"""Find and fix what makes Flutter treat frontend/android as a deprecated V1-embedding project.

    python scripts/migrate_android_embedding.py            # inspect only (no changes)
    python scripts/migrate_android_embedding.py --apply    # back up android/, then apply the minimal fixes

Standard library only. It changes ONLY the V1 leftovers below and never touches the application ID/namespace,
permissions, Gradle plugins, dependencies, assets, lib/ or test/:

  1. android/app/src/main/AndroidManifest.xml
     * missing                                   -> report (run `flutter create . --platforms=android`, which only
                                                    creates MISSING files, or restore it from the repo)
     * <application android:name="io.flutter.app.FlutterApplication">   -> "${applicationName}"
     * <meta-data android:name="flutterEmbedding"> missing or value "1"  -> value "2"
     * activity/application names using io.flutter.app.*                  -> reported (not guessed)
  2. MainActivity.kt / MainActivity.java that extends the V1 io.flutter.app.FlutterActivity or calls
     GeneratedPluginRegistrant.registerWith(this)
                                                 -> V2 `FlutterActivity` (same package), only when it contains
                                                    nothing else; custom code is reported for manual migration
  3. A committed android/app/src/main/java/io/flutter/plugins/GeneratedPluginRegistrant.java written for V1
     (registerWith(PluginRegistry ...))          -> moved into the backup (Flutter regenerates the V2 one on build)

The detection mirrors the Flutter tool's rule: the project is V2 only if the main manifest exists, its
<application> is not io.flutter.app.FlutterApplication, and it has <meta-data android:name="flutterEmbedding"
android:value="2"/>.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

V1_APP = "io.flutter.app.FlutterApplication"
V1_ACTIVITY = "io.flutter.app.FlutterActivity"
EMBEDDING_META = '<meta-data android:name="flutterEmbedding" android:value="2"/>'
SKIP_BACKUP = {"build", ".gradle", ".cxx", ".idea", "local.properties"}


@dataclass
class Report:
    findings: list[str] = field(default_factory=list)  # V1 triggers found
    changes: list[str] = field(default_factory=list)  # what --apply changed (or would change)
    manual: list[str] = field(default_factory=list)  # needs a human decision
    info: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------------------------- manifest
def embedding_version(manifest: str) -> tuple[int, str]:
    """(version, reason) using the Flutter tool's rule."""
    for m in re.finditer(r"<application\b[^>]*>", manifest, re.DOTALL):
        if re.search(r'android:name\s*=\s*"io\.flutter\.app\.FlutterApplication"', m.group(0)):
            return 1, f"<application> uses {V1_APP}"
    for m in re.finditer(r"<meta-data\b[^>]*>", manifest, re.DOTALL):
        tag = m.group(0)
        if re.search(r'android:name\s*=\s*"flutterEmbedding"', tag):
            value = re.search(r'android:value\s*=\s*"([^"]*)"', tag)
            if value and value.group(1) == "2":
                return 2, 'has <meta-data android:name="flutterEmbedding" android:value="2"/>'
            if value and value.group(1) == "1":
                return 1, 'flutterEmbedding meta-data has android:value="1"'
    return 1, 'no <meta-data android:name="flutterEmbedding" android:value="2"/>'


def fix_manifest(text: str) -> tuple[str, list[str]]:
    """Minimal text edits (formatting, comments and every other attribute are preserved)."""
    notes: list[str] = []
    new, n = re.subn(
        r'(<application\b[^>]*?android:name\s*=\s*")io\.flutter\.app\.FlutterApplication(")',
        r"\g<1>${applicationName}\2",
        text,
        flags=re.DOTALL,
    )
    if n:
        notes.append(f'<application android:name>: {V1_APP} -> "${{applicationName}}"')
    text = new
    meta = [
        m
        for m in re.finditer(r"<meta-data\b[^>]*>", text, re.DOTALL)
        if re.search(r'android:name\s*=\s*"flutterEmbedding"', m.group(0))
    ]
    if meta:
        tag = meta[0].group(0)
        fixed = (
            re.sub(r'android:value\s*=\s*"[^"]*"', 'android:value="2"', tag)
            if "android:value" in tag
            else tag.replace("<meta-data", '<meta-data android:value="2"', 1)
        )
        if fixed != tag:
            text = text[: meta[0].start()] + fixed + text[meta[0].end() :]
            notes.append('flutterEmbedding meta-data value set to "2"')
    else:
        close = text.rfind("</application>")
        if close < 0:
            raise ValueError("no </application> element: the manifest needs manual review")
        line_start = text.rfind("\n", 0, close) + 1
        indent = re.match(r"[ \t]*", text[line_start:close]).group(0)  # type: ignore[union-attr]
        text = text[:close] + f"    {EMBEDDING_META}\n{indent}" + text[close:]
        notes.append(f"added {EMBEDDING_META} inside <application>")
    return text, notes


# ----------------------------------------------------------------------------------------- MainActivity
KOTLIN_V2 = (
    "package {pkg}\n\nimport io.flutter.embedding.android.FlutterActivity\n\nclass MainActivity : FlutterActivity()\n"
)
JAVA_V2 = "package {pkg};\n\nimport io.flutter.embedding.android.FlutterActivity;\n\npublic class MainActivity extends FlutterActivity {{\n}}\n"
V1_BOILERPLATE = [
    r"^\s*package\s+[\w.]+;?\s*$",
    r"^\s*import\s+(android\.os\.Bundle|io\.flutter\.app\.FlutterActivity|io\.flutter\.plugins\.GeneratedPluginRegistrant|io\.flutter\.embedding\.android\.FlutterActivity|androidx\.annotation\.NonNull|io\.flutter\.embedding\.engine\.FlutterEngine);?\s*$",
    r"^\s*(public\s+)?class\s+MainActivity\b.*$",
    r"^\s*(@Override|override)\b.*onCreate.*$",
    r"^\s*@Override\s*$",
    r"^\s*(protected\s+)?(void\s+)?(fun\s+)?onCreate\s*\(.*$",
    r"^\s*super\.onCreate\(.*$",
    r"^\s*GeneratedPluginRegistrant\.registerWith\(.*$",
    r"^\s*[{}]\s*$",
    r"^\s*$",
]


def is_v1_activity(text: str) -> bool:
    return V1_ACTIVITY in text or bool(re.search(r"GeneratedPluginRegistrant\.registerWith\(\s*this\s*\)", text))


def migrate_activity(path: Path) -> tuple[str | None, str]:
    """Return (new text, note). new text is None when the file has custom code and must be migrated by hand."""
    text = path.read_text(encoding="utf-8")
    pkg = re.search(r"^\s*package\s+([\w.]+)", text, re.MULTILINE)
    if not pkg:
        return None, f"{path.name}: no package line"
    custom = [ln for ln in text.splitlines() if not any(re.match(p, ln) for p in V1_BOILERPLATE)]
    if custom:
        return None, f"{path.name}: has custom code ({custom[0].strip()[:60]!r}...), migrate by hand"
    template = KOTLIN_V2 if path.suffix == ".kt" else JAVA_V2
    return (
        template.format(pkg=pkg.group(1)),
        f"{path.name}: V1 FlutterActivity -> V2 io.flutter.embedding.android.FlutterActivity (package {pkg.group(1)} kept)",
    )


# ------------------------------------------------------------------------------------------------ main
def inspect_and_fix(frontend: Path, apply: bool) -> Report:
    r = Report()
    android = frontend / "android"
    if not android.is_dir():
        r.manual.append(f"{android} does not exist: run `flutter create . --platforms=android` first")
        return r
    app = android / "app"
    gradle = [
        p.relative_to(android).as_posix()
        for p in (
            android / "build.gradle",
            android / "build.gradle.kts",
            app / "build.gradle",
            app / "build.gradle.kts",
        )
        if p.exists()
    ]
    r.info.append("Gradle files: " + (", ".join(gradle) or "none found"))
    for g in (app / "build.gradle.kts", app / "build.gradle"):
        if g.exists():
            s = g.read_text(encoding="utf-8")
            ids = re.findall(r'(applicationId|namespace)\s*=?\s*"([^"]+)"', s)
            r.info.append(f"{g.name}: " + ", ".join(f"{k}={v}" for k, v in ids) + " (not changed)")
            if "apply from:" in s and "flutter.gradle" in s:
                r.manual.append(
                    f"{g.name} applies Flutter's Gradle plugin imperatively (`apply from: ...flutter.gradle`); this is a separate migration, not done here"
                )

    backup: Path | None = None

    def ensure_backup() -> None:
        nonlocal backup
        if apply and backup is None:
            backup = frontend / f".android_backup_{datetime.now().astimezone().strftime('%Y%m%d_%H%M%S')}"
            shutil.copytree(android, backup, ignore=lambda d, names: [n for n in names if n in SKIP_BACKUP])
            r.info.append(f"backup of android/ written to {backup.name}/")

    manifest = app / "src" / "main" / "AndroidManifest.xml"
    if not manifest.exists():
        r.findings.append(f"{manifest.relative_to(frontend)} is missing (Flutter then assumes V1)")
        r.manual.append(
            "restore android/app/src/main/AndroidManifest.xml from the repository ZIP (it declares the V2 embedding, INTERNET and RECORD_AUDIO)"
        )
    else:
        text = manifest.read_text(encoding="utf-8")
        version, reason = embedding_version(text)
        r.info.append(f"main manifest: V{version} ({reason})")
        if re.search(r"io\.flutter\.app\.(?!FlutterApplication)\w+", text):
            r.manual.append("main manifest references other io.flutter.app.* (V1) classes: replace them by hand")
        if version == 1:
            r.findings.append(f"main manifest: {reason}")
            new, notes = fix_manifest(text)
            r.changes += [f"AndroidManifest.xml: {n}" for n in notes]
            if apply:
                ensure_backup()
                manifest.write_text(new, encoding="utf-8")
                after, why = embedding_version(new)
                assert after == 2, why

    for d in ("debug", "profile"):
        m = app / "src" / d / "AndroidManifest.xml"
        if m.exists() and re.search(r"io\.flutter\.app\.", m.read_text(encoding="utf-8")):
            r.manual.append(f"src/{d}/AndroidManifest.xml references io.flutter.app.* (V1)")

    for act in sorted((app / "src" / "main").rglob("MainActivity.*")):
        if act.suffix not in (".kt", ".java"):
            continue
        text = act.read_text(encoding="utf-8")
        rel = act.relative_to(frontend).as_posix()
        if not is_v1_activity(text):
            r.info.append(f"{rel}: V2 (ok)")
            continue
        r.findings.append(
            f"{rel}: V1 activity (io.flutter.app.FlutterActivity / GeneratedPluginRegistrant.registerWith(this))"
        )
        migrated, note = migrate_activity(act)
        if migrated is None:
            r.manual.append(note)
            continue
        r.changes.append(note)
        if apply:
            ensure_backup()
            act.write_text(migrated, encoding="utf-8")

    for reg in (app / "src" / "main").rglob("GeneratedPluginRegistrant.java"):
        text = reg.read_text(encoding="utf-8")
        if (
            re.search(r"registerWith\s*\(\s*PluginRegistry\b", text)
            or "io.flutter.plugin.common.PluginRegistry" in text
        ):
            rel = reg.relative_to(frontend).as_posix()
            r.findings.append(f"{rel}: committed V1 GeneratedPluginRegistrant (Flutter regenerates a V2 one)")
            r.changes.append(f"{rel}: moved into the backup")
            if apply:
                ensure_backup()
                reg.unlink()
    return r


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="back up android/ and apply the fixes (default: inspect only)")
    ap.add_argument("--frontend", type=Path, default=Path(__file__).resolve().parents[1] / "frontend")
    args = ap.parse_args(argv)
    r = inspect_and_fix(args.frontend.resolve(), args.apply)
    for title, items in (
        ("Info", r.info),
        ("V1 triggers found", r.findings),
        ("Changes" + ("" if args.apply else " (dry run: rerun with --apply)"), r.changes),
        ("Needs manual action", r.manual),
    ):
        print(f"\n{title}:")
        for line in items or ["none"]:
            print(f"  - {line}")
    if not r.findings and not r.manual:
        print(
            "\nNo V1 embedding leftovers found in android/. If `flutter build apk -v` still fails, the verbose log names the reason "
            "(search for 'flutterEmbedding' or 'v1 embedding') - please send that line."
        )
    return 1 if r.manual else 0


if __name__ == "__main__":
    sys.exit(main())
