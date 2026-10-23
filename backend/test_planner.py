
import pytest

from planner import replan_activity


@pytest.fixture
def sample_trip():
    return {
        "trip_days": 4,
        "budget_limit": 30000,
        "fixed_costs": {
            "transport": 9000,
            "accommodation": 9000,
            "food": 6000,
        },
        "activities": [
            {"name": "Solang Valley", "estimated_cost": 1500, "day": 1},
            {"name": "Local sightseeing", "estimated_cost": 1000, "day": 2},
            {"name": "Mall Road", "estimated_cost": 500, "day": 3},
        ],
    }


def test_replace_activity_preserves_other_activities(sample_trip):
    result = replan_activity(
        **sample_trip,
        target_index=1,
        new_activity_name="Adventure Park",
        new_activity_cost=2000,
        new_activity_day=2,
    )

    assert result["activities"][1]["name"] == "Adventure Park"
    assert result["activities"][1]["estimated_cost"] == 2000
    assert result["activities"][0]["name"] == "Solang Valley"
    assert result["activities"][2]["name"] == "Mall Road"


def test_recalculate_total(sample_trip):
    result = replan_activity(
        **sample_trip,
        target_index=1,
        new_activity_name="Adventure Park",
        new_activity_cost=2000,
        new_activity_day=2,
    )

    assert result["fixed_total"] == 24000
    assert result["activity_total"] == 4000
    assert result["estimated_total"] == 28000
    assert result["remaining_budget"] == 2000
    assert result["within_budget"] is True


def test_detect_budget_violation(sample_trip):
    result = replan_activity(
        **sample_trip,
        target_index=1,
        new_activity_name="Luxury Adventure",
        new_activity_cost=10000,
        new_activity_day=2,
    )

    assert result["estimated_total"] == 36000
    assert result["within_budget"] is False
    assert result["over_budget_by"] == 6000
    assert result["status"] == "over_budget"


def test_reject_invalid_activity_index(sample_trip):
    with pytest.raises(ValueError):
        replan_activity(
            **sample_trip,
            target_index=10,
            new_activity_name="Adventure Park",
            new_activity_cost=2000,
            new_activity_day=2,
        )


def test_reject_invalid_day(sample_trip):
    with pytest.raises(ValueError):
        replan_activity(
            **sample_trip,
            target_index=1,
            new_activity_name="Adventure Park",
            new_activity_cost=2000,
            new_activity_day=5,
        )


def test_reject_negative_cost(sample_trip):
    with pytest.raises(ValueError):
        replan_activity(
            **sample_trip,
            target_index=1,
            new_activity_name="Adventure Park",
            new_activity_cost=-100,
            new_activity_day=2,
        )
