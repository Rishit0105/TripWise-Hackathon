from typing import Any
from mcp.server.fastmcp import FastMCP
from database import create_trip, get_trip, update_trip
from planner import (
    replan_activity as run_replan,
    suggest_activity_alternatives as run_suggestions,
)


mcp = FastMCP(
    "TripWise",
    json_response=True,
    host="127.0.0.1",
    port=8001,
)


@mcp.tool()
def create_travel_trip(
    destination: str,
    travelers: int,
    trip_days: int,
    budget_limit: float,
    fixed_costs: dict[str, float],
    activities: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create and persist a travel trip with its budget and activities."""

    if not destination.strip():
        raise ValueError("Destination cannot be empty.")
    if not 1 <= travelers <= 20:
        raise ValueError("Travelers must be between 1 and 20.")
    if not 1 <= trip_days <= 30:
        raise ValueError("Trip duration must be between 1 and 30 days.")
    if budget_limit <= 0:
        raise ValueError("Budget must be greater than zero.")
    if not activities:
        raise ValueError("At least one activity is required.")

    for category, cost in fixed_costs.items():
        if (
            not category.strip()
            or not isinstance(cost, (int, float))
            or isinstance(cost, bool)
            or cost < 0
        ):
            raise ValueError("Invalid fixed-cost category or amount.")

    for activity in activities:
        if not isinstance(activity.get("name"), str) or not activity["name"].strip():
            raise ValueError("Each activity needs a name.")

        cost = activity.get("estimated_cost")
        day = activity.get("day")

        if (
            not isinstance(cost, (int, float))
            or isinstance(cost, bool)
            or cost < 0
        ):
            raise ValueError("Activity costs must be non-negative.")

        if (
            not isinstance(day, int)
            or isinstance(day, bool)
            or not 1 <= day <= trip_days
        ):
            raise ValueError("Activity day must be within the trip duration.")

    trip = create_trip({
        "destination": destination.strip(),
        "travelers": travelers,
        "trip_days": trip_days,
        "budget_limit": budget_limit,
        "fixed_costs": fixed_costs,
        "activities": activities,
    })

    return {"message": "Trip created.", "trip": trip}


@mcp.tool()
def get_travel_trip(trip_id: str) -> dict[str, Any]:
    """Retrieve a saved trip by its unique ID."""

    trip = get_trip(trip_id)

    if trip is None:
        return {"error": "Trip not found.", "trip_id": trip_id}

    return trip


@mcp.tool()
def replan_travel_activity(
    trip_id: str,
    target_index: int,
    new_activity_name: str,
    new_activity_cost: float,
    new_activity_day: int,
) -> dict[str, Any]:
    """Replace a saved trip activity, recalculate costs, and persist the change."""

    trip = get_trip(trip_id)

    if trip is None:
        return {"error": "Trip not found.", "trip_id": trip_id}

    result = run_replan(
        trip_days=trip["trip_days"],
        budget_limit=trip["budget_limit"],
        fixed_costs=trip["fixed_costs"],
        activities=trip["activities"],
        target_index=target_index,
        new_activity_name=new_activity_name,
        new_activity_cost=new_activity_cost,
        new_activity_day=new_activity_day,
    )

    updated_trip = update_trip(
        trip_id,
        result["fixed_costs"],
        result["activities"],
    )

    if updated_trip is None:
        return {"error": "Trip could not be saved.", "trip_id": trip_id}

    return {
        "trip": updated_trip,
        "budget": {
            "estimated_total": result["estimated_total"],
            "budget_limit": result["budget_limit"],
            "remaining_budget": result["remaining_budget"],
            "over_budget_by": result["over_budget_by"],
            "within_budget": result["within_budget"],
        },
    }


@mcp.tool()
def suggest_travel_alternatives(
    trip_id: str,
    target_index: int,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Suggest alternative activities ranked by their resulting trip cost."""

    trip = get_trip(trip_id)

    if trip is None:
        return {"error": "Trip not found.", "trip_id": trip_id}

    return run_suggestions(
        trip_days=trip["trip_days"],
        budget_limit=trip["budget_limit"],
        fixed_costs=trip["fixed_costs"],
        activities=trip["activities"],
        target_index=target_index,
        candidates=candidates,
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http")