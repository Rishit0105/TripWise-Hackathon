
from fastapi import FastAPI
from pydantic import BaseModel, Field
from budget import allocate_budget, check_budget, calculate_trip_estimate
from planner import replan_activity, suggest_activity_alternatives, recommend_destination_activities
from database import create_trip, get_trip, update_trip
from fastapi.middleware.cors import CORSMiddleware
from intent_parser import extract_trip_intent
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")



app = FastAPI(
    title="TripWise API",
    description="A constraint-aware AI travel planning system.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class TripRequest(BaseModel):
    destination: str = Field(min_length=2, max_length=100)
    duration_days: int = Field(ge=1, le=30)
    travelers: int = Field(ge=1, le=20)
    total_budget: float = Field(gt=0)
    currency: str = "INR"


class ActivityInput(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    estimated_cost: float = Field(ge=0)
    day: int = Field(ge=1)


class ReplanRequest(BaseModel):
    trip_days: int = Field(ge=1, le=30)
    budget_limit: float = Field(gt=0)
    fixed_costs: dict[str, float]
    activities: list[ActivityInput] = Field(min_length=1, max_length=100)
    target_index: int = Field(ge=0)
    new_activity_name: str = Field(min_length=1, max_length=150)
    new_activity_cost: float = Field(ge=0)
    new_activity_day: int = Field(ge=1)


    
class CreateSavedTripRequest(BaseModel):
    destination: str = Field(min_length=2, max_length=100)
    travelers: int = Field(ge=1, le=20)
    trip_days: int = Field(ge=1, le=30)
    budget_limit: float = Field(gt=0)
    fixed_costs: dict[str, float]
    activities: list[ActivityInput] = Field(
        min_length=1,
        max_length=100,
    )


class SavedReplanRequest(BaseModel):
    target_index: int = Field(ge=0)
    new_activity_name: str = Field(min_length=1, max_length=150)
    new_activity_cost: float = Field(ge=0)
    new_activity_day: int = Field(ge=1, le=30)


class AlternativeInput(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    estimated_cost: float = Field(ge=0)
    day: int | None = Field(default=None, ge=1, le=30)


class AlternativesRequest(BaseModel):
    target_index: int = Field(ge=0)
    candidates: list[AlternativeInput] = Field(
        min_length=1,
        max_length=30,
    )


@app.get("/", tags=["System"])
def root():
    return {
        "message": "Welcome to TripWise",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", response_model=HealthResponse, tags=["System"])
def health_check():
    return HealthResponse(
        status="healthy",
        service="tripwise-api",
        version="0.1.0",
    )


@app.post("/trips/validate", tags=["Trips"])
def validate_trip(trip: TripRequest):
    budget_per_person = trip.total_budget / trip.travelers
    budget_per_person_per_day = (
        budget_per_person / trip.duration_days
    )

    return {
        "destination": trip.destination,
        "duration_days": trip.duration_days,
        "travelers": trip.travelers,
        "total_budget": trip.total_budget,
        "currency": trip.currency,
        "budget_per_person": round(budget_per_person, 2),
        "budget_per_person_per_day": round(
            budget_per_person_per_day, 2
        ),
        "status": "valid",
    }



@app.post("/trips/budget-breakdown", tags=["Trips"])
def budget_breakdown(trip: TripRequest):
    allocation = allocate_budget(trip.total_budget)

    return {
        "destination": trip.destination,
        "currency": trip.currency,
        "allocation": {
            "transport": allocation.transport,
            "accommodation": allocation.accommodation,
            "food": allocation.food,
            "activities": allocation.activities,
            "emergency": allocation.emergency,
        },
        "total_allocated": allocation.total,
    }


@app.post("/trips/check-budget", tags=["Trips"])
def budget_check(payload: dict):
    try:
        return check_budget(
            float(payload["budget_limit"]),
            float(payload["estimated_cost"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc


from fastapi import HTTPException


@app.post("/trips/replan-activity", tags=["Trips"])
def replan_trip_activity(request: ReplanRequest):
    try:
        return replan_activity(
            trip_days=request.trip_days,
            budget_limit=request.budget_limit,
            fixed_costs=request.fixed_costs,
            activities=[
                activity.model_dump()
                for activity in request.activities
            ],
            target_index=request.target_index,
            new_activity_name=request.new_activity_name,
            new_activity_cost=request.new_activity_cost,
            new_activity_day=request.new_activity_day,
        )
    
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc



@app.post("/trips", tags=["Persistent Trips"])
def create_saved_trip(request: CreateSavedTripRequest):
    if any(
        not key.strip()
        or not isinstance(cost, (int, float))
        or isinstance(cost, bool)
        or cost < 0
        for key, cost in request.fixed_costs.items()
    ):
        raise HTTPException(
            status_code=422,
            detail="Fixed cost categories must have non-negative costs.",
        )

    if any(
        activity.day > request.trip_days
        for activity in request.activities
    ):
        raise HTTPException(
            status_code=422,
            detail="An activity day exceeds the trip duration.",
        )

    trip = create_trip({
        "destination": request.destination,
        "travelers": request.travelers,
        "trip_days": request.trip_days,
        "budget_limit": request.budget_limit,
        "fixed_costs": request.fixed_costs,
        "activities": [
            activity.model_dump()
            for activity in request.activities
        ],
    })

    return {
        "message": "Trip created successfully.",
        "trip": trip,
    }


@app.get("/trips/{trip_id}", tags=["Persistent Trips"])
def read_saved_trip(trip_id: str):
    trip = get_trip(trip_id)

    if trip is None:
        raise HTTPException(
            status_code=404,
            detail="Trip not found.",
        )

    return trip


@app.post(
    "/trips/{trip_id}/replan",
    tags=["Persistent Trips"],
)
def replan_saved_trip(
    trip_id: str,
    request: SavedReplanRequest,
):
    trip = get_trip(trip_id)

    if trip is None:
        raise HTTPException(
            status_code=404,
            detail="Trip not found.",
        )

    try:
        result = replan_activity(
            trip_days=trip["trip_days"],
            budget_limit=trip["budget_limit"],
            fixed_costs=trip["fixed_costs"],
            activities=trip["activities"],
            target_index=request.target_index,
            new_activity_name=request.new_activity_name,
            new_activity_cost=request.new_activity_cost,
            new_activity_day=request.new_activity_day,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    updated_trip = update_trip(
        trip_id,
        result["fixed_costs"],
        result["activities"],
    )

    if updated_trip is None:
        raise HTTPException(
            status_code=404,
            detail="Trip not found.",
        )

    return {
        "message": "Trip replanned and saved.",
        "trip": updated_trip,
        "budget": {
            "estimated_total": result["estimated_total"],
            "budget_limit": result["budget_limit"],
            "remaining_budget": result["remaining_budget"],
            "over_budget_by": result["over_budget_by"],
            "within_budget": result["within_budget"],
        },
    }


@app.post(
    "/trips/{trip_id}/alternatives",
    tags=["Persistent Trips"],
)
def find_trip_alternatives(
    trip_id: str,
    request: AlternativesRequest,
):
    trip = get_trip(trip_id)

    if trip is None:
        raise HTTPException(
            status_code=404,
            detail="Trip not found.",
        )

    try:
        result = suggest_activity_alternatives(
            trip_days=trip["trip_days"],
            budget_limit=trip["budget_limit"],
            fixed_costs=trip["fixed_costs"],
            activities=trip["activities"],
            target_index=request.target_index,
            candidates=[
                candidate.model_dump(exclude_none=True)
                for candidate in request.candidates
            ],
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    return result


@app.post("/trips/parse-intent")
def parse_trip_intent(payload: dict):
    message = payload.get("message", "").strip()

    if not message:
        return {
            "error": "Message is required"
        }

    return extract_trip_intent(message)

# Live transport/accommodation search adapter. Existing scraper source files remain unchanged.
from pydantic import BaseModel, Field
from typing import Literal
from live_prices import get_live_trip_options


class LiveOptionsRequest(BaseModel):
    origin: str = Field(min_length=2, max_length=100)
    destination: str = Field(min_length=2, max_length=100)
    travel_date: str = Field(description="Outbound travel date in DD/MM/YYYY format")
    return_date: str | None = Field(default=None, description="Optional return date in DD/MM/YYYY format")
    travelers: int = Field(default=1, ge=1, le=20)
    transport_modes: list[Literal["flight", "bus", "train", "cab"]] = Field(
        default_factory=lambda: ["flight", "bus", "train", "cab"],
        max_length=4,
    )
    include_accommodation: bool = True
    route_information: dict[str, float] | None = None


@app.post("/trips/live-options", tags=["Live Prices"])
def live_trip_options(request: LiveOptionsRequest):
    # Reject stale dates before invoking scrapers. Dates arrive in DD/MM/YYYY format.
    from datetime import datetime as _datetime

    try:
        departure_date = _datetime.strptime(request.travel_date, "%d/%m/%Y").date()
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="Departure date must be a valid date in DD/MM/YYYY format.",
        ) from exc

    if departure_date < _datetime.now().date():
        raise HTTPException(
            status_code=422,
            detail="Departure date is in the past. Choose a future date.",
        )

    if request.return_date:
        try:
            return_date_value = _datetime.strptime(request.return_date, "%d/%m/%Y").date()
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="Return date must be a valid date in DD/MM/YYYY format.",
            ) from exc
        if return_date_value < departure_date:
            raise HTTPException(
                status_code=422,
                detail="Return date cannot be earlier than departure date.",
            )

    try:
        return get_live_trip_options(
            origin=request.origin,
            destination=request.destination,
            travel_date=request.travel_date,
            return_date=request.return_date,
            travelers=request.travelers,
            transport_modes=request.transport_modes,
            include_accommodation=request.include_accommodation,
            route_information=request.route_information,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        # Avoid crashing the API if an external site or browser fails.
        raise HTTPException(
            status_code=502,
            detail=f"Live option search failed: {exc}",
        ) from exc



# Destination-aware activity recommendations and transparent trip-cost estimate.
class ActivityRecommendationsRequest(BaseModel):
    destination: str = Field(min_length=2, max_length=100)
    interests: list[Literal["adventure", "food", "nature", "culture"]] = Field(
        default_factory=list, max_length=4
    )
    budget_per_person: float | None = Field(default=None, ge=0)
    limit: int = Field(default=12, ge=1, le=30)


class TripEstimateRequest(BaseModel):
    budget_limit: float = Field(gt=0)
    travelers: int = Field(ge=1, le=20)
    trip_days: int = Field(ge=1, le=30)
    transport_total: float = Field(default=0, ge=0)
    accommodation_amount: float | None = Field(default=None, ge=0)
    accommodation_price_basis: Literal["unknown", "total_stay", "per_night_per_room"] = "unknown"
    rooms: int = Field(default=1, ge=1, le=20)
    food_per_person_per_day: float = Field(default=600, ge=0)
    local_transport_per_person_per_day: float = Field(default=250, ge=0)
    activities_total: float = Field(default=0, ge=0)
    contingency_rate: float = Field(default=0.10, ge=0, le=1)


@app.post("/trips/activities", tags=["Planning"])
def destination_activities(request: ActivityRecommendationsRequest):
    """Return destination-specific suggestions with clearly labeled estimated costs."""
    try:
        return recommend_destination_activities(
            destination=request.destination,
            interests=request.interests,
            budget_per_person=request.budget_per_person,
            limit=request.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/trips/estimate-budget", tags=["Planning"])
def estimate_trip_budget(request: TripEstimateRequest):
    """Calculate a transparent estimate from selected trip costs."""
    try:
        return calculate_trip_estimate(
            budget_limit=request.budget_limit,
            travelers=request.travelers,
            trip_days=request.trip_days,
            transport_total=request.transport_total,
            accommodation_amount=request.accommodation_amount,
            accommodation_price_basis=request.accommodation_price_basis,
            rooms=request.rooms,
            food_per_person_per_day=request.food_per_person_per_day,
            local_transport_per_person_per_day=request.local_transport_per_person_per_day,
            activities_total=request.activities_total,
            contingency_rate=request.contingency_rate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# Conversational copilot. The model is optional; without a configured key,
# a deterministic fallback still supports budget questions and safe previews.
from copilot import chat_with_copilot


class CopilotChatRequest(BaseModel):
    trip_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2000)


@app.post("/copilot/chat", tags=["Copilot"])
def copilot_chat(request: CopilotChatRequest):
    try:
        return chat_with_copilot(request.trip_id, request.message)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
