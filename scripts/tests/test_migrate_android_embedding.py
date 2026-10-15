"""Tests for scripts/migrate_android_embedding.py on synthetic V1/V2 Android projects."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("mig", HERE.parent / "migrate_android_embedding.py")
assert spec and spec.loader
mig = importlib.util.module_from_spec(spec)
sys.modules["mig"] = mig  # dataclasses need the module registered
spec.loader.exec_module(mig)
REPO_FRONTEND = HERE.parents[1] / "frontend"

V1_MANIFEST = """<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.harvestique.harvestique">
    <uses-permission android:name="android.permission.INTERNET"/>
    <uses-permission android:name="android.permission.RECORD_AUDIO"/>
    <application
        android:name="io.flutter.app.FlutterApplication"
        android:label="Harvestique"
        android:icon="@mipmap/ic_launcher">
        <activity android:name=".MainActivity" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN"/>
                <category android:name="android.intent.category.LAUNCHER"/>
            </intent-filter>
        </activity>
    </application>
</manifest>
"""
V1_JAVA = """package com.harvestique.harvestique;

import android.os.Bundle;
import io.flutter.app.FlutterActivity;
import io.flutter.plugins.GeneratedPluginRegistrant;

public class MainActivity extends FlutterActivity {
  @Override
  protected void onCreate(Bundle savedInstanceState) {
    super.onCreate(savedInstanceState);
    GeneratedPluginRegistrant.registerWith(this);
  }
}
"""
V1_REGISTRANT = """package io.flutter.plugins;

import io.flutter.plugin.common.PluginRegistry;

public final class GeneratedPluginRegistrant {
  public static void registerWith(PluginRegistry registry) {
  }
}
"""
GRADLE = 'android {\n    namespace = "com.harvestique.harvestique"\n    defaultConfig {\n        applicationId = "com.harvestique.harvestique"\n    }\n}\n'


def write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def project(
    tmp: Path,
    manifest: str | None = V1_MANIFEST,
    activity: tuple[str, str] | None = ("java", V1_JAVA),
    registrant: bool = True,
) -> Path:
    fe = tmp / "frontend"
    main = fe / "android/app/src/main"
    write(fe / "android/app/build.gradle.kts", GRADLE)
    write(fe / "android/build.gradle.kts", "// root\n")
    write(
        fe / "android/app/src/debug/AndroidManifest.xml",
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application android:usesCleartextTraffic="true"/></manifest>\n',
    )
    if manifest is not None:
        write(main / "AndroidManifest.xml", manifest)
    if activity:
        lang, text = activity
        write(main / f"{lang}/com/harvestique/harvestique/MainActivity.{'kt' if lang == 'kotlin' else 'java'}", text)
    if registrant:
        write(main / "java/io/flutter/plugins/GeneratedPluginRegistrant.java", V1_REGISTRANT)
    return fe


def snapshot(fe: Path) -> dict[str, str]:
    return {
        p.relative_to(fe).as_posix(): p.read_text(encoding="utf-8") for p in (fe / "android").rglob("*") if p.is_file()
    }


def test_classic_v1_project_is_migrated_minimally(tmp_path):
    fe = project(tmp_path)
    before = snapshot(fe)
    r = mig.inspect_and_fix(fe, apply=True)
    assert len(r.findings) == 3 and not r.manual
    man = (fe / "android/app/src/main/AndroidManifest.xml").read_text()
    assert mig.embedding_version(man)[0] == 2
    assert 'android:name="${applicationName}"' in man and mig.V1_APP not in man
    # everything else in the manifest is preserved
    for keep in (
        'package="com.harvestique.harvestique"',
        "android.permission.INTERNET",
        "android.permission.RECORD_AUDIO",
        'android:label="Harvestique"',
        "android.intent.action.MAIN",
    ):
        assert keep in man
    act = (fe / "android/app/src/main/java/com/harvestique/harvestique/MainActivity.java").read_text()
    assert (
        act.startswith("package com.harvestique.harvestique;") and "io.flutter.embedding.android.FlutterActivity" in act
    )
    assert "io.flutter.app" not in act and "GeneratedPluginRegistrant" not in act
    assert not (fe / "android/app/src/main/java/io/flutter/plugins/GeneratedPluginRegistrant.java").exists()
    after = snapshot(fe)
    assert after["android/app/build.gradle.kts"] == before["android/app/build.gradle.kts"]  # IDs untouched
    assert after["android/app/src/debug/AndroidManifest.xml"] == before["android/app/src/debug/AndroidManifest.xml"]
    backup = next(fe.glob(".android_backup_*"))
    assert (backup / "app/src/main/AndroidManifest.xml").read_text() == V1_MANIFEST
    assert (backup / "app/src/main/java/io/flutter/plugins/GeneratedPluginRegistrant.java").exists()


def test_only_missing_meta_data_adds_one_line_and_nothing_else(tmp_path):
    manifest = V1_MANIFEST.replace(
        'android:name="io.flutter.app.FlutterApplication"', 'android:name="${applicationName}"'
    )
    kotlin_v2 = "package com.harvestique.harvestique\n\nimport io.flutter.embedding.android.FlutterActivity\n\nclass MainActivity : FlutterActivity()\n"
    fe = project(tmp_path, manifest, ("kotlin", kotlin_v2), registrant=False)
    before = snapshot(fe)
    r = mig.inspect_and_fix(fe, apply=True)
    assert r.findings == ['main manifest: no <meta-data android:name="flutterEmbedding" android:value="2"/>']
    after = snapshot(fe)
    changed = [k for k in after if after[k] != before.get(k)]
    assert changed == ["android/app/src/main/AndroidManifest.xml"]
    old, new = before[changed[0]].splitlines(), after[changed[0]].splitlines()
    assert len(new) == len(old) + 1 and [ln for ln in new if ln not in old] == [
        '        <meta-data android:name="flutterEmbedding" android:value="2"/>'
    ]
    assert (
        new.index("    </application>")
        == new.index('        <meta-data android:name="flutterEmbedding" android:value="2"/>') + 1
    )


def test_value_1_is_corrected(tmp_path):
    manifest = V1_MANIFEST.replace(
        'android:name="io.flutter.app.FlutterApplication"', 'android:name="${applicationName}"'
    ).replace(
        "    </application>",
        '        <meta-data android:name="flutterEmbedding" android:value="1"/>\n    </application>',
    )
    fe = project(tmp_path, manifest, None, registrant=False)
    mig.inspect_and_fix(fe, apply=True)
    man = (fe / "android/app/src/main/AndroidManifest.xml").read_text()
    assert 'android:value="2"' in man and 'android:value="1"' not in man and man.count("flutterEmbedding") == 1


def test_dry_run_changes_nothing(tmp_path):
    fe = project(tmp_path)
    before = snapshot(fe)
    r = mig.inspect_and_fix(fe, apply=False)
    assert len(r.findings) == 3 and len(r.changes) >= 3
    assert snapshot(fe) == before and not list(fe.glob(".android_backup_*"))


def test_second_run_is_a_no_op(tmp_path):
    fe = project(tmp_path)
    mig.inspect_and_fix(fe, apply=True)
    after = snapshot(fe)
    r = mig.inspect_and_fix(fe, apply=True)
    assert r.findings == [] and r.changes == [] and snapshot(fe) == after
    assert len(list(fe.glob(".android_backup_*"))) == 1


def test_custom_activity_code_is_reported_not_rewritten(tmp_path):
    custom = V1_JAVA.replace(
        "    GeneratedPluginRegistrant.registerWith(this);",
        '    GeneratedPluginRegistrant.registerWith(this);\n    new MethodChannel(getFlutterView(), "x");',
    )
    fe = project(tmp_path, activity=("java", custom))
    r = mig.inspect_and_fix(fe, apply=True)
    assert any("custom code" in m for m in r.manual)
    assert (fe / "android/app/src/main/java/com/harvestique/harvestique/MainActivity.java").read_text() == custom


def test_missing_manifest_is_reported(tmp_path):
    fe = project(tmp_path, manifest=None, activity=None, registrant=False)
    r = mig.inspect_and_fix(fe, apply=True)
    assert any("missing" in f for f in r.findings) and r.manual


def test_the_repository_android_folder_is_already_v2(tmp_path):
    fe = tmp_path / "frontend"
    shutil.copytree(REPO_FRONTEND / "android", fe / "android")
    before = snapshot(fe)
    r = mig.inspect_and_fix(fe, apply=True)
    assert r.findings == [] and r.changes == [] and r.manual == [] and snapshot(fe) == before
    assert mig.embedding_version((fe / "android/app/src/main/AndroidManifest.xml").read_text())[0] == 2


@pytest.mark.parametrize(
    ("manifest", "version"),
    [
        (
            '<manifest><application android:name="${applicationName}"><meta-data android:name="flutterEmbedding" android:value="2"/></application></manifest>',
            2,
        ),
        (
            '<manifest><application android:name="io.flutter.app.FlutterApplication"><meta-data android:name="flutterEmbedding" android:value="2"/></application></manifest>',
            1,
        ),
        ("<manifest><application/></manifest>", 1),
        (
            '<manifest><application><meta-data\n   android:value="2"\n   android:name="flutterEmbedding"/></application></manifest>',
            2,
        ),
    ],
)
def test_detection_matches_the_flutter_rule(manifest, version):
    assert mig.embedding_version(manifest)[0] == version
