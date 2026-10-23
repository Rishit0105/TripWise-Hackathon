
import pytest

from budget import allocate_budget, check_budget


def test_budget_allocation():
    result = allocate_budget(30000)

    assert result.transport == 9000
    assert result.accommodation == 9000
    assert result.food == 6000
    assert result.activities == 3000
    assert result.emergency == 3000
    assert result.total == 30000


def test_budget_within_limit():
    result = check_budget(30000, 25000)

    assert result["within_budget"] is True
    assert result["remaining"] == 5000
    assert result["over_budget_by"] == 0


def test_budget_exceeded():
    result = check_budget(30000, 34000)

    assert result["within_budget"] is False
    assert result["remaining"] == 0
    assert result["over_budget_by"] == 4000


def test_invalid_budget():
    with pytest.raises(ValueError):
        allocate_budget(0)


def test_negative_estimated_cost():
    with pytest.raises(ValueError):
        check_budget(30000, -1000)
