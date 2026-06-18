from decimal import Decimal

import pytest

from storage_service.domain import DomainError, ensure_transition, make_slug, normalize_quantity


def test_powder_unit_conversion():
    assert normalize_quantity("POWDER", "1", "pounds") == (Decimal("7000.000000"), "grains")
    assert normalize_quantity("POWDER", "1", "ounces") == (Decimal("437.500000"), "grains")
    assert normalize_quantity("POWDER", "10", "grams") == (Decimal("154.323584"), "grains")


def test_count_conversion_requires_whole_count():
    assert normalize_quantity("PRIMER", 100, "count") == (Decimal("100"), "count")
    with pytest.raises(DomainError) as error:
        normalize_quantity("PRIMER", "1.5", "count")
    assert error.value.code == "invalid_quantity"


def test_slug_collision_regenerates(monkeypatch):
    choices = iter(["craft", "anvil", "craft", "anvil", "forge", "ridge"])
    monkeypatch.setattr("storage_service.domain.random.choice", lambda _values: next(choices))
    assert make_slug(lambda slug: slug == "craft-anvil") == "forge-ridge"


def test_invalid_transition_is_rejected():
    with pytest.raises(DomainError) as error:
        ensure_transition("UNDER PRODUCTION", "USED", {"UNDER PRODUCTION": {"IN STORAGE"}}, "Batch")
    assert error.value.code == "invalid_transition"

