import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.crop_cycles import CropCycleUpdate
from app.schemas.farms import FarmCreate, FarmRead, FarmUpdate, PlotCreate


def errors(model, data):
    with pytest.raises(ValidationError) as exc:
        model.model_validate(data)
    return {".".join(map(str, e["loc"])): e["msg"] for e in exc.value.errors()}


def test_decimals_are_exact_in_python_and_numbers_in_json():
    farm = FarmCreate.model_validate({"name": "A", "total_area_acres": 12.5})
    assert farm.total_area_acres == Decimal("12.5")
    assert json.loads(farm.model_dump_json())["total_area_acres"] == 12.5  # number, not "12.500"


@pytest.mark.parametrize("area", [0, -1, "abc", None, 1e9, 1.2345])
def test_area_must_be_positive_and_bounded(area):
    assert "total_area_acres" in errors(FarmCreate, {"name": "A", "total_area_acres": area})


def test_plot_area_positive():
    assert "area_acres" in errors(PlotCreate, {"name": "P", "area_acres": 0})


def test_coordinates_must_be_paired_and_in_range():
    assert errors(FarmCreate, {"name": "A", "total_area_acres": 1, "latitude": 12.3})
    assert "latitude" in errors(FarmCreate, {"name": "A", "total_area_acres": 1, "latitude": 91, "longitude": 10})
    assert "longitude" in errors(FarmCreate, {"name": "A", "total_area_acres": 1, "latitude": 10, "longitude": 181})
    FarmCreate.model_validate({"name": "A", "total_area_acres": 1, "latitude": 12.295, "longitude": 76.639})


def test_unknown_and_ownership_fields_are_rejected():
    assert errors(FarmCreate, {"name": "A", "total_area_acres": 1, "owner_id": "x"})
    assert errors(CropCycleUpdate, {"crop_id": "x"})  # a cycle's crop and plot are immutable
    assert errors(CropCycleUpdate, {"plot_id": "x"})


def test_patch_null_is_rejected_only_for_required_columns():
    assert "name" in errors(FarmUpdate, {"name": None})
    assert "total_area_acres" in errors(FarmUpdate, {"total_area_acres": None})
    assert "status" in errors(CropCycleUpdate, {"status": None})
    cleared = FarmUpdate.model_validate({"village": None})  # nullable column: clearing is legitimate
    assert cleared.model_fields_set == {"village"}


def test_patch_distinguishes_omitted_from_null():
    assert FarmUpdate.model_validate({}).model_dump(exclude_unset=True) == {}
    assert FarmUpdate.model_validate({"notes": None}).model_dump(exclude_unset=True) == {"notes": None}


def test_strings_are_trimmed_and_blank_rejected():
    assert FarmCreate.model_validate({"name": "  Hill Farm  ", "total_area_acres": 1}).name == "Hill Farm"
    assert "name" in errors(FarmCreate, {"name": "   ", "total_area_acres": 1})


def test_read_model_reads_orm_like_objects():
    class Row:
        id = "7d6e2b7a-8f3a-4c43-9b8a-0a3a7a0d5a11"
        name, village, district, state, notes = "A", None, None, None, None
        latitude = longitude = None
        total_area_acres = Decimal("3.250")
        is_active = True
        from datetime import UTC, datetime

        created_at = updated_at = datetime.now(UTC)

    out = json.loads(FarmRead.model_validate(Row()).model_dump_json())
    assert out["total_area_acres"] == 3.25 and out["latitude"] is None
