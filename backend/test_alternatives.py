
import pytest

from planner import suggest_activity_alternatives


@pytest.fixture
def trip():
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
        "target_index": 1,
    }


def test_feasible_alternatives_ranked_first(trip):
    result = suggest_activity_alternatives(
        **trip,
        candidates=[
            {"name": "Luxury Adventure", "estimated_cost": 10000},
            {"name": "Nature Walk", "estimated_cost": 0},
            {"name": "Adventure Park", "estimated_cost": 2000},
        ],
    )

    options = result["alternatives"]

    assert options[0]["name"] == "Nature Walk"
    assert options[0]["estimated_total"] == 26000
    assert options[0]["within_budget"] is True
    assert result["feasible_alternatives_count"] == 2


def test_over_budget_alternative_reports_shortfall(trip):
    result = suggest_activity_alternatives(
        **trip,
        candidates=[
            {"name": "Luxury Adventure", "estimated_cost": 10000},
        ],
    )

    option = result["alternatives"][0]

    assert option["estimated_total"] == 36000
    assert option["over_budget_by"] == 6000
    assert option["within_budget"] is False


def test_original_trip_is_not_modified(trip):
    original_activities = [dict(a) for a in trip["activities"]]

    suggest_activity_alternatives(
        **trip,
        candidates=[
            {"name": "Nature Walk", "estimated_cost": 0},
        ],
    )

    assert trip["activities"] == original_activities


def test_reject_empty_candidates(trip):
    with pytest.raises(ValueError):
        suggest_activity_alternatives(**trip, candidates=[])


def test_reject_negative_candidate_cost(trip):
    with pytest.raises(ValueError):
        suggest_activity_alternatives(
            **trip,
            candidates=[
                {"name": "Invalid Activity", "estimated_cost": -100},
            ],
        )


def test_alternatives_keep_existing_day_by_default(trip):
    result = suggest_activity_alternatives(
        **trip,
        candidates=[
            {"name": "Nature Walk", "estimated_cost": 0},
        ],
    )

    assert result["alternatives"][0]["day"] == 2
