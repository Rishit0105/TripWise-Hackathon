
from dataclasses import dataclass


@dataclass
class BudgetBreakdown:
    transport: float
    accommodation: float
    food: float
    activities: float
    emergency: float

    @property
    def total(self) -> float:
        return round(
            self.transport
            + self.accommodation
            + self.food
            + self.activities
            + self.emergency,
            2,
        )


def allocate_budget(total_budget: float) -> BudgetBreakdown:
    
    if total_budget <= 0:
        raise ValueError("Budget must be greater than zero.")

    return BudgetBreakdown(
        transport=round(total_budget * 0.30, 2),
        accommodation=round(total_budget * 0.30, 2),
        food=round(total_budget * 0.20, 2),
        activities=round(total_budget * 0.10, 2),
        emergency=round(total_budget * 0.10, 2),
    )


def check_budget(
    budget_limit: float,
    estimated_cost: float,
    ) -> dict:

    if budget_limit <= 0:
        raise ValueError("Budget limit must be greater than zero.")

    if estimated_cost < 0:
        raise ValueError("Estimated cost cannot be negative.")

    difference = round(budget_limit - estimated_cost, 2)

    return {
        "budget_limit": round(budget_limit, 2),
        "estimated_cost": round(estimated_cost, 2),
        "remaining": max(difference, 0),
        "over_budget_by": max(-difference, 0),
        "within_budget": difference >= 0,
    }


def calculate_trip_estimate(
    *,
    budget_limit: float,
    travelers: int,
    trip_days: int,
    transport_total: float = 0,
    accommodation_amount: float | None = None,
    accommodation_price_basis: str = "unknown",
    rooms: int = 1,
    food_per_person_per_day: float = 600,
    local_transport_per_person_per_day: float = 250,
    activities_total: float = 0,
    contingency_rate: float = 0.10,
) -> dict:
    """Estimate costs from selected inputs, without silently treating unknown hotel prices as totals.

    accommodation_price_basis:
      - "total_stay": amount is the total accommodation cost for the whole group
      - "per_night_per_room": amount is the nightly rate per room; multiply by nights and rooms
      - "unknown": report the amount as unpriced and exclude it from the numeric total
    """
    if budget_limit <= 0:
        raise ValueError("Budget limit must be greater than zero.")
    if not isinstance(travelers, int) or isinstance(travelers, bool) or travelers < 1:
        raise ValueError("Travelers must be a positive integer.")
    if not isinstance(trip_days, int) or isinstance(trip_days, bool) or trip_days < 1:
        raise ValueError("Trip days must be a positive integer.")
    if not isinstance(rooms, int) or isinstance(rooms, bool) or rooms < 1:
        raise ValueError("Rooms must be a positive integer.")
    if not 0 <= contingency_rate <= 1:
        raise ValueError("Contingency rate must be between 0 and 1.")

    numeric_inputs = {
        "transport_total": transport_total,
        "food_per_person_per_day": food_per_person_per_day,
        "local_transport_per_person_per_day": local_transport_per_person_per_day,
        "activities_total": activities_total,
    }
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0 for v in numeric_inputs.values()):
        raise ValueError("Costs must be non-negative numbers.")
    if accommodation_amount is not None and (
        not isinstance(accommodation_amount, (int, float))
        or isinstance(accommodation_amount, bool)
        or accommodation_amount < 0
    ):
        raise ValueError("Accommodation amount must be a non-negative number or null.")

    if accommodation_price_basis not in {"unknown", "total_stay", "per_night_per_room"}:
        raise ValueError("Accommodation price basis must be unknown, total_stay, or per_night_per_room.")

    nights = max(trip_days - 1, 0)
    if accommodation_amount is None or accommodation_price_basis == "unknown":
        accommodation_total = None
    elif accommodation_price_basis == "total_stay":
        accommodation_total = round(float(accommodation_amount), 2)
    else:
        accommodation_total = round(float(accommodation_amount) * nights * rooms, 2)

    food_total = round(food_per_person_per_day * travelers * trip_days, 2)
    local_transport_total = round(local_transport_per_person_per_day * travelers * trip_days, 2)
    known_subtotal = round(
        transport_total + food_total + local_transport_total + activities_total
        + (accommodation_total or 0),
        2,
    )
    contingency = round(known_subtotal * contingency_rate, 2)
    estimated_total = round(known_subtotal + contingency, 2)
    difference = round(budget_limit - estimated_total, 2)

    missing = []
    if accommodation_total is None:
        missing.append("accommodation_total")
    return {
        "currency": "INR",
        "budget_limit": round(budget_limit, 2),
        "travelers": travelers,
        "trip_days": trip_days,
        "nights": nights,
        "costs": {
            "transport": round(float(transport_total), 2),
            "accommodation": accommodation_total,
            "food": food_total,
            "local_transport": local_transport_total,
            "activities": round(float(activities_total), 2),
            "contingency": contingency,
        },
        "known_cost_subtotal": known_subtotal,
        "estimated_total_excluding_unpriced_items": estimated_total,
        "remaining_budget_before_unpriced_items": max(difference, 0),
        "over_budget_by_before_unpriced_items": max(-difference, 0),
        "within_budget_before_unpriced_items": difference >= 0,
        "unpriced_items": missing,
        "budget_status": (
            "incomplete_price_data" if missing else
            ("within_budget" if difference >= 0 else "over_budget")
        ),
        "notes": [
            "Food and local transport are planning estimates, not provider quotes.",
            "Contingency is calculated on known costs only.",
            *(
                ["Accommodation is excluded from the numeric total because its price basis is unknown."]
                if accommodation_total is None else []
            ),
        ],
    }
