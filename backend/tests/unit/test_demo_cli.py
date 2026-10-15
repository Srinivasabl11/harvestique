"""The demo CLI must not let the startup catalog seed pre-empt the crop its scenario creates (POST /crops -> 409)."""

from __future__ import annotations

from app.cli import demo


def test_demo_cli_turns_off_the_startup_catalog_seed(monkeypatch, settings):
    seen: dict[str, bool] = {}
    real_build = demo.build_container

    def spy(s):
        seen["seed"] = s.seed_crop_catalog_on_startup
        return real_build(s)

    # a non-test environment, where the API would otherwise seed an empty catalog at startup
    monkeypatch.setattr(demo, "get_settings", lambda: settings.model_copy(update={"app_env": "development"}))
    monkeypatch.setattr(demo, "build_container", spy)
    monkeypatch.setattr(demo, "run_demo", lambda client, container: {})
    assert demo.main([]) == 0
    assert seen["seed"] is False
