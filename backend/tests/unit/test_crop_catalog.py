"""The A-Z crop master catalogue: no duplicates, every group covered, synonyms, no invented Kannada names, and the
crop context the photo check receives."""

from __future__ import annotations

from collections import Counter

from app.cli.seed_crops import seed_payloads
from app.core.enums import CropGroup
from app.domain.crop_catalog import EXISTING, GROUPS, NEW, group_and_part
from app.domain.crop_health_validation import validation_for
from app.domain.crop_profiles import PART_GUIDANCE, context_for, crop_matches


def test_no_name_or_alias_belongs_to_two_crops():
    words = Counter(w.lower() for p in seed_payloads() for w in (p.name, *p.aliases))
    assert [w for w, c in words.items() if c > 1] == []


def test_every_agricultural_group_is_covered_and_matches_the_enum():
    groups = {p.crop_group for p in seed_payloads()}
    assert set(GROUPS) == {g.value for g in CropGroup} == {g.value for g in groups if g}


def test_the_88_existing_crops_keep_their_names_and_all_get_metadata():
    existing = [p for p in seed_payloads() if p.name in EXISTING]
    assert len(existing) == 88 and all(p.scientific_name and p.crop_group for p in existing)
    assert len(seed_payloads()) == 88 + len(NEW)


def test_new_crops_have_no_invented_kannada_names_and_say_durations_are_indicative():
    new = {c.name for c in NEW}
    for p in seed_payloads():
        if p.name in new:
            assert p.local_name is None, p.name
            assert p.notes and ("Indicative" in p.notes or "Perennial" in p.notes or "fungus" in p.notes), p.name


def test_synonyms_from_the_master_list_point_to_one_crop():
    owner = {w.lower(): p.name for p in seed_payloads() for w in (p.name, *p.aliases)}
    for alias, crop in {
        "finger millet": "Ragi",
        "sorghum": "Jowar",
        "chikoo": "Sapota",
        "arhar": "Red Gram",
        "pigeon pea": "Red Gram",
        "urad": "Black Gram",
        "eggplant": "Brinjal",
        "lady's finger": "Okra",
        "peanut": "Groundnut",
        "tapioca": "Cassava",
        "moringa": "Drumstick",
        "amla": "Aonla",
        "corn": "Maize",
        "rice": "Paddy",
        "pearl millet": "Bajra",
        "chickpea": "Bengal Gram",
        "mung bean": "Green Gram",
        "cocoyam": "Xanthosoma",
    }.items():
        assert owner[alias] == crop, alias
    assert "gooseberry" not in owner and "orange" not in owner  # ambiguous names are not used as aliases


def test_parts_and_groups_for_listed_and_admin_added_crops():
    assert group_and_part("Potato", "vegetable", None) == ("roots_tubers", "tuber")
    assert group_and_part("Ginger", "spice", None) == ("spices", "rhizome")
    assert group_and_part("Mushroom", "other", None) == ("mushrooms", "fungus")
    assert group_and_part("Some New Crop", "fruit", None) == ("fruits", "fruit")  # admin-added: from its category
    assert group_and_part("Some New Crop", "other", "fodder") == ("fodder", "whole_plant")


def test_crop_context_and_the_models_crop_guess():
    ragi = context_for(
        "Ragi",
        category="cereal",
        group="millets",
        local_name="ರಾಗಿ",
        aliases=["finger millet"],
        scientific="Eleusine coracana",
    )
    assert ragi.part == "grain" and "eleusine" in ragi.names and not ragi.specialist_only
    assert crop_matches("finger millet", ragi) is True and crop_matches("Eleusine coracana plant", ragi) is True
    assert crop_matches("tomato", ragi) is False
    assert (
        crop_matches("unknown", ragi) is None and crop_matches("leaf", ragi) is None and crop_matches("", ragi) is None
    )
    potato = context_for("Potato", category="vegetable", group=None)
    assert "Soil on the surface" in potato.prompt_note() and potato.part == "tuber"
    assert context_for("Mushroom", category="other", group="mushrooms").specialist_only
    assert set(PART_GUIDANCE) >= {"leaf", "fruit", "tuber", "bulb", "rhizome", "corm", "root", "flower", "grain"}


def test_validation_status_reports_measurements_only():
    tomato = validation_for("Tomato")
    assert tomato["health_evaluation_completed"] and tomato["healthy_photos"] == 4 and tomato["problem_photos"] == 28
    assert tomato["verdict"] == "insufficient_evidence"  # 4 web photos of healthy tomato leaves are not enough
    groundnut = validation_for("Groundnut")
    assert groundnut["verdict"] == "not_reliable" and groundnut["healthy_recall"] == 0.0  # 10/10 healthy flagged
    mango = validation_for("Mango")
    assert mango["verdict"] == "insufficient_evidence" and not mango["health_evaluation_completed"]
    assert not any(validation_for(name)["verdict"] == "reliable" for name in ("Tomato", "Groundnut", "Apple"))


def test_identification_evidence_is_recorded_without_overstating_it():
    tomato, groundnut, mango = validation_for("Tomato"), validation_for("Groundnut"), validation_for("Mango")
    assert tomato["crop_identification_tested"] and tomato["identification"][0]["crop_correct"] == 3
    assert groundnut["identification"][0] == {
        "dataset": groundnut["identification"][0]["dataset"],
        "photos": 20,
        "crop_correct": 6,
        "part_correct": 20,
    }
    assert not mango["crop_identification_tested"]
