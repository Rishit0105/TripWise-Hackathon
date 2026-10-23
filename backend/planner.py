
from typing import Any


def replan_activity(
    *,
    trip_days: int,
    budget_limit: float,
    fixed_costs: dict[str, float],
    activities: list[dict[str, Any]],
    target_index: int,
    new_activity_name: str,
    new_activity_cost: float,
    new_activity_day: int,
) -> dict[str, Any]:
    """Replace one activity and recalculate the trip budget."""

    if trip_days < 1:
        raise ValueError("Trip must have at least one day.")

    if budget_limit <= 0:
        raise ValueError("Budget must be greater than zero.")

    if not 0 <= target_index < len(activities):
        raise ValueError("Target activity does not exist.")

    if not new_activity_name.strip():
        raise ValueError("Activity name cannot be empty.")

    if new_activity_cost < 0:
        raise ValueError("Activity cost cannot be negative.")

    if not 1 <= new_activity_day <= trip_days:
        raise ValueError("Activity day is outside the trip dates.")

    if any(
        not isinstance(cost, (int, float))
        or isinstance(cost, bool)
        or cost < 0
        for cost in fixed_costs.values()
    ):
        raise ValueError("Fixed costs must be non-negative numbers.")

    updated_activities = [dict(a) for a in activities]

    updated_activities[target_index] = {
        **updated_activities[target_index],
        "name": new_activity_name.strip(),
        "estimated_cost": round(new_activity_cost, 2),
        "day": new_activity_day,
    }

    activity_total = round(
        sum(float(a["estimated_cost"]) for a in updated_activities),
        2,
    )
    fixed_total = round(sum(fixed_costs.values()), 2)
    estimated_total = round(fixed_total + activity_total, 2)
    difference = round(budget_limit - estimated_total, 2)

    return {
        "activities": updated_activities,
        "fixed_costs": fixed_costs,
        "activity_total": activity_total,
        "fixed_total": fixed_total,
        "estimated_total": estimated_total,
        "budget_limit": round(budget_limit, 2),
        "remaining_budget": max(difference, 0),
        "over_budget_by": max(-difference, 0),
        "within_budget": difference >= 0,
        "status": "within_budget" if difference >= 0 else "over_budget",
    }


def suggest_activity_alternatives(
    *,
    trip_days: int,
    budget_limit: float,
    fixed_costs: dict[str, float],
    activities: list[dict[str, Any]],
    target_index: int,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Rank replacement activities by budget feasibility and total cost."""

    if trip_days < 1 or budget_limit <= 0:
        raise ValueError("Trip duration and budget must be positive.")

    if not 0 <= target_index < len(activities):
        raise ValueError("Target activity does not exist.")

    if not candidates:
        raise ValueError("At least one alternative is required.")

    for cost in fixed_costs.values():
        if (
            not isinstance(cost, (int, float))
            or isinstance(cost, bool)
            or cost < 0
        ):
            raise ValueError("Fixed costs must be non-negative numbers.")

    fixed_total = sum(fixed_costs.values())
    current_activity = activities[target_index]

    if not 1 <= current_activity["day"] <= trip_days:
        raise ValueError("Existing activity has an invalid day.")

    current_activity_total = sum(
        activity["estimated_cost"] for activity in activities
    )
    current_total = round(fixed_total + current_activity_total, 2)

    alternatives = []
    seen_names = set()

    for candidate in candidates:
        name = candidate.get("name")
        cost = candidate.get("estimated_cost")
        day = candidate.get("day", current_activity["day"])

        if not isinstance(name, str) or not name.strip():
            raise ValueError("Each alternative needs a valid name.")

        if (
            not isinstance(cost, (int, float))
            or isinstance(cost, bool)
            or cost < 0
        ):
            raise ValueError("Alternative costs must be non-negative.")

        if (
            not isinstance(day, int)
            or isinstance(day, bool)
            or not 1 <= day <= trip_days
        ):
            raise ValueError("Alternative has an invalid trip day.")

        normalized_name = name.strip()

        if normalized_name.casefold() in seen_names:
            continue

        seen_names.add(normalized_name.casefold())

        revised_activity_total = (
            current_activity_total
            - current_activity["estimated_cost"]
            + cost
        )
        revised_total = round(fixed_total + revised_activity_total, 2)
        difference = round(budget_limit - revised_total, 2)

        alternatives.append({
            "name": normalized_name,
            "estimated_cost": round(cost, 2),
            "day": day,
            "estimated_total": revised_total,
            "remaining_budget": max(difference, 0),
            "over_budget_by": max(-difference, 0),
            "within_budget": difference >= 0,
            "change_in_total": round(revised_total - current_total, 2),
        })

    # Prefer feasible options, then the lowest total trip cost.
    alternatives.sort(
        key=lambda item: (
            not item["within_budget"],
            item["estimated_total"],
            item["name"].casefold(),
        )
    )

    feasible_count = sum(
        item["within_budget"] for item in alternatives
    )

    return {
        "current_total": current_total,
        "budget_limit": round(budget_limit, 2),
        "current_within_budget": current_total <= budget_limit,
        "feasible_alternatives_count": feasible_count,
        "alternatives": alternatives,
        "message": (
            "Alternatives that fit the budget are listed first."
            if feasible_count
            else "No supplied alternative fits the budget."
        ),
    }


# Curated starter catalogue for destination-aware activity recommendations.
# Prices are planning estimates per person, not live ticket quotes.
_DESTINATION_ACTIVITIES: dict[str, list[dict[str, Any]]] = {
    "jaipur": [
        {"name": "Amber Fort", "category": "culture", "estimated_cost": 200, "duration_hours": 2.5, "description": "Explore Jaipur's hilltop fort and courtyards."},
        {"name": "Hawa Mahal (Palace of Winds)", "category": "culture", "estimated_cost": 100, "duration_hours": 1.0, "description": "See the iconic pink sandstone facade and nearby old city."},
        {"name": "City Palace", "category": "culture", "estimated_cost": 300, "duration_hours": 2.0, "description": "Visit royal courtyards, galleries and museum rooms."},
        {"name": "Jantar Mantar", "category": "culture", "estimated_cost": 200, "duration_hours": 1.5, "description": "Explore the historic astronomical instruments."},
        {"name": "Johari Bazaar food walk", "category": "food", "estimated_cost": 400, "duration_hours": 2.0, "description": "Sample local snacks and browse traditional markets."},
        {"name": "Nahargarh Fort sunset", "category": "nature", "estimated_cost": 150, "duration_hours": 2.0, "description": "Enjoy panoramic views over Jaipur."},
        {"name": "Jaipur cycling or guided heritage walk", "category": "adventure", "estimated_cost": 700, "duration_hours": 2.0, "description": "Explore the city actively with a guided route."},
        {"name": "Central Park stroll", "category": "nature", "estimated_cost": 0, "duration_hours": 1.0, "description": "Take a low-cost walk through a large city park."},
    ],
    "manali": [
        {"name": "Hadimba Devi Temple and cedar forest", "category": "culture", "estimated_cost": 0, "duration_hours": 1.5, "description": "Visit the wooden temple in a cedar forest."},
        {"name": "Old Manali cafe and food walk", "category": "food", "estimated_cost": 500, "duration_hours": 2.0, "description": "Try local Himachali dishes and independent cafes."},
        {"name": "Jogini Waterfall hike", "category": "adventure", "estimated_cost": 150, "duration_hours": 3.0, "description": "Take a scenic hike; check trail and weather conditions."},
        {"name": "Vashisht hot springs area", "category": "culture", "estimated_cost": 50, "duration_hours": 1.5, "description": "Visit the village temple area and hot-spring complex."},
        {"name": "Solang Valley", "category": "adventure", "estimated_cost": 500, "duration_hours": 3.0, "description": "Mountain scenery and optional paid activities."},
        {"name": "Beas River riverside walk", "category": "nature", "estimated_cost": 0, "duration_hours": 1.0, "description": "Enjoy a free riverside walk; stay away from fast water."},
        {"name": "Naggar Castle and village", "category": "culture", "estimated_cost": 100, "duration_hours": 2.5, "description": "Explore historic architecture and village views."},
    ],
    "rishikesh": [
        {"name": "Triveni Ghat evening aarti", "category": "culture", "estimated_cost": 0, "duration_hours": 1.0, "description": "Attend the riverside evening ceremony."},
        {"name": "Ram Jhula and riverside walk", "category": "nature", "estimated_cost": 0, "duration_hours": 1.5, "description": "Walk across the suspension bridge and along the river."},
        {"name": "Local vegetarian food walk", "category": "food", "estimated_cost": 350, "duration_hours": 2.0, "description": "Sample local snacks and vegetarian cafes."},
        {"name": "Guided rafting trip", "category": "adventure", "estimated_cost": 1200, "duration_hours": 3.0, "description": "Use a licensed operator and check current river conditions."},
        {"name": "Beatles Ashram", "category": "culture", "estimated_cost": 200, "duration_hours": 2.0, "description": "Explore the former ashram's murals and forest paths."},
        {"name": "Neer Garh Waterfall hike", "category": "adventure", "estimated_cost": 100, "duration_hours": 2.5, "description": "Hike to a waterfall; check trail conditions first."},
    ],
    "delhi": [
        {"name": "Humayun's Tomb", "category": "culture", "estimated_cost": 40, "duration_hours": 2.0, "description": "Explore Mughal architecture and landscaped gardens."},
        {"name": "National Museum", "category": "culture", "estimated_cost": 20, "duration_hours": 2.5, "description": "Browse Indian art, archaeology and historical collections."},
        {"name": "Chandni Chowk food walk", "category": "food", "estimated_cost": 500, "duration_hours": 2.0, "description": "Try well-known Old Delhi street food with care about hygiene."},
        {"name": "Lodhi Garden walk", "category": "nature", "estimated_cost": 0, "duration_hours": 1.5, "description": "Walk among landscaped lawns and historic tombs."},
        {"name": "Qutub Minar complex", "category": "culture", "estimated_cost": 40, "duration_hours": 2.0, "description": "Visit the UNESCO-listed monument complex."},
        {"name": "Delhi cycling heritage tour", "category": "adventure", "estimated_cost": 900, "duration_hours": 2.5, "description": "Explore selected neighbourhoods with a guided cycling tour."},
    ],
    "shimla": [
        {"name": "The Ridge and Mall Road walk", "category": "nature", "estimated_cost": 0, "duration_hours": 1.5, "description": "Explore the pedestrian centre and hill views."},
        {"name": "Jakhu Temple", "category": "culture", "estimated_cost": 0, "duration_hours": 2.0, "description": "Visit the hilltop temple; use the marked route or transport."},
        {"name": "Himachali food tasting", "category": "food", "estimated_cost": 450, "duration_hours": 1.5, "description": "Try regional dishes at a local restaurant."},
        {"name": "Kufri outdoor day trip", "category": "adventure", "estimated_cost": 800, "duration_hours": 4.0, "description": "A mountain outing; verify transport and activity charges."},
        {"name": "Viceregal Lodge", "category": "culture", "estimated_cost": 100, "duration_hours": 1.5, "description": "See the historic building and grounds; check access hours."},
    ],
    "goa": [
        {"name": "Old Goa churches", "category": "culture", "estimated_cost": 0, "duration_hours": 2.0, "description": "Explore historic churches and Portuguese-era architecture."},
        {"name": "Local Goan seafood or vegetarian food trail", "category": "food", "estimated_cost": 700, "duration_hours": 2.0, "description": "Try regional Goan dishes at local eateries."},
        {"name": "South Goa beach day", "category": "nature", "estimated_cost": 150, "duration_hours": 3.0, "description": "Relax at a beach; transport and rentals cost extra."},
        {"name": "Guided kayaking or paddle activity", "category": "adventure", "estimated_cost": 1000, "duration_hours": 2.0, "description": "Choose a reputable operator and check sea/weather conditions."},
        {"name": "Fontainhas heritage walk", "category": "culture", "estimated_cost": 200, "duration_hours": 1.5, "description": "Walk through Panjim's colourful Latin Quarter."},
    ],
    "amritsar": [
        {"name": "Golden Temple", "category": "culture", "estimated_cost": 0, "duration_hours": 2.0, "description": "Visit the Harmandir Sahib; follow visitor etiquette."},
        {"name": "Jallianwala Bagh", "category": "culture", "estimated_cost": 0, "duration_hours": 1.0, "description": "Learn about a major event in India's history."},
        {"name": "Amritsari food walk", "category": "food", "estimated_cost": 500, "duration_hours": 2.0, "description": "Try local kulcha, chole and traditional sweets."},
        {"name": "Partition Museum", "category": "culture", "estimated_cost": 250, "duration_hours": 1.5, "description": "Explore oral histories and exhibits about Partition."},
        {"name": "Wagah-Attari border ceremony", "category": "culture", "estimated_cost": 200, "duration_hours": 3.0, "description": "Plan travel time and verify entry arrangements."},
    ],
}



def _google_places_activities(
    destination: str,
    interests: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Fetch, deduplicate, and rank Google Places activity candidates.

    Searches each requested interest independently and follows up to three pages
    per query (up to 60 results per query where Google has more results).
    Google Places does not guarantee an exhaustive list of every place.
    """
    import json
    import math
    import os
    import urllib.error
    import urllib.request

    api_key = os.getenv("GOOGLE_PLACES_API_KEY") or os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return []

    interest_queries = {
        "adventure": (
            "outdoor adventure activities hiking trekking trails rafting "
            "zipline climbing safari and adventure sports"
        ),
        "food": (
            "local restaurants regional cuisine street food stalls food tours "
            "and food experiences"
        ),
        "nature": (
            "botanical gardens nature reserves wildlife sanctuaries waterfalls "
            "lakes scenic viewpoints and nature trails"
        ),
        "culture": (
            "historic forts palaces monuments museums temples heritage sites "
            "and cultural landmarks"
        ),
    }
    selected = [interest for interest in ("adventure", "food", "nature", "culture")
                if interest in interests]
    if not selected:
        selected = ["culture", "nature"]

    field_mask = (
        "places.id,places.displayName,places.formattedAddress,"
        "places.googleMapsUri,places.rating,places.userRatingCount,"
        "places.types,places.primaryType,places.editorialSummary,places.location,nextPageToken"
    )
    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    # A broad candidate pool lets the final ranking select stronger places
    # instead of simply returning the first few Google results.
    page_size = 20
    max_pages_per_interest = 3

    food_types = {
        "restaurant", "cafe", "bakery", "meal_takeaway", "meal_delivery",
        "food", "ice_cream_shop", "food_court", "bar", "coffee_shop",
    }
    adventure_types = {
        "adventure_sports_center", "hiking_area", "ski_resort", "rafting",
        "rock_climbing", "go_karting_venue", "amusement_park",
        "amusement_center", "paintball_center", "sports_activity_location",
        "off_roading_area",
    }
    nature_types = {
        "national_park", "wildlife_park", "wildlife_refuge", "nature_preserve",
        "botanical_garden", "garden", "park", "beach", "waterfall",
        "campground", "hiking_area", "lake",
    }
    culture_types = {
        "museum", "art_gallery", "hindu_temple", "church", "mosque",
        "synagogue", "historical_landmark", "monument", "fortress", "palace",
        "tourist_attraction",
    }
    # Generic service listings often represent booking agencies rather than
    # places or activities. Keep them only when Google also identifies a
    # concrete activity/attraction type.
    agency_types = {
        "travel_agency", "tour_agency", "tour_operator", "travel_service",
        "tourist_information_center",
    }
    concrete_activity_types = (
        food_types | adventure_types | nature_types | culture_types
        | {"zoo", "aquarium"}
    )
    category_types = {
        "food": food_types,
        "adventure": adventure_types,
        "nature": nature_types | {"zoo", "aquarium"},
        "culture": culture_types,
    }

    # Use the requested locality as a strict guardrail. Text Search can return
    # similarly named businesses from other cities, even when the query names
    # the intended destination. The first comma-separated part is treated as
    # the city/locality (e.g. "Jaipur, Rajasthan" -> "Jaipur").
    locality = destination.split(",", 1)[0].strip().casefold()

    # Resolve the destination's city-centre coordinate once. Distance is an
    # approximate straight-line distance, not driving distance; if geocoding is
    # unavailable, recommendations still work and distance remains unknown.
    destination_center = None
    distance_center_source = "unavailable"
    try:
        from urllib.parse import quote

        geocode_url = (
            "https://maps.googleapis.com/maps/api/geocode/json"
            f"?address={quote(destination + ', India')}&key={api_key}"
        )
        geocode_request = urllib.request.Request(geocode_url, method="GET")
        with urllib.request.urlopen(geocode_request, timeout=8) as response:
            geocode_payload = json.loads(response.read().decode("utf-8"))
        if geocode_payload.get("status") == "OK" and geocode_payload.get("results"):
            location = geocode_payload["results"][0]["geometry"]["location"]
            destination_center = (float(location["lat"]), float(location["lng"]))
            distance_center_source = "google_geocoding_api"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        destination_center = None

    # Geocoding API may not be enabled for a key that can use Places API.
    # Fall back to Places Text Search, but only accept an explicitly locality-like
    # result so we do not mistake a random business for the city centre.
    if destination_center is None:
        try:
            fallback_body = json.dumps({
                "textQuery": f"{destination}, India",
                "pageSize": 5,
                "languageCode": "en",
                "regionCode": "IN",
            }).encode("utf-8")
            fallback_request = urllib.request.Request(
                "https://places.googleapis.com/v1/places:searchText",
                data=fallback_body,
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": api_key,
                    "X-Goog-FieldMask": (
                        "places.displayName,places.formattedAddress,places.location,"
                        "places.types,places.primaryType"
                    ),
                },
                method="POST",
            )
            with urllib.request.urlopen(fallback_request, timeout=8) as response:
                fallback_payload = json.loads(response.read().decode("utf-8"))
            locality_types = {
                "locality", "administrative_area_level_1",
                "administrative_area_level_2", "administrative_area_level_3",
                "postal_town",
            }
            for place in fallback_payload.get("places", []):
                place_name = ((place.get("displayName") or {}).get("text") or "").casefold()
                place_address = (place.get("formattedAddress") or "").casefold()
                place_types = set(place.get("types") or [])
                if place.get("primaryType"):
                    place_types.add(place["primaryType"])
                location = place.get("location") or {}
                if (
                    locality in place_name
                    and locality in place_address
                    and place_types & locality_types
                    and isinstance(location.get("latitude"), (int, float))
                    and isinstance(location.get("longitude"), (int, float))
                ):
                    destination_center = (
                        float(location["latitude"]), float(location["longitude"])
                    )
                    distance_center_source = "google_places_locality_fallback"
                    break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            destination_center = None

    def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        earth_radius_km = 6371.0
        lat1_r, lon1_r, lat2_r, lon2_r = map(
            math.radians, (lat1, lon1, lat2, lon2)
        )
        dlat = lat2_r - lat1_r
        dlon = lon2_r - lon1_r
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
        )
        return 2 * earth_radius_km * math.asin(math.sqrt(min(1.0, a)))

    for interest in selected:
        page_token = None
        for _ in range(max_pages_per_interest):
            body_data = {
                "textQuery": f"{interest_queries[interest]} in {destination}, India",
                "pageSize": page_size,
                "languageCode": "en",
                "regionCode": "IN",
            }
            if page_token:
                body_data["pageToken"] = page_token
            body = json.dumps(body_data).encode("utf-8")
            request = urllib.request.Request(
                "https://places.googleapis.com/v1/places:searchText",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": api_key,
                    "X-Goog-FieldMask": field_mask,
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=12) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                # Use the curated catalogue if Google is unavailable.
                return []

            for place in payload.get("places", []):
                place_id = place.get("id")
                name = (place.get("displayName") or {}).get("text")
                address = (place.get("formattedAddress") or "").strip()

                # Reject results whose formatted address does not contain the
                # requested locality. This deliberately favors local precision
                # over returning a full list contaminated with other cities.
                if not name or not address or locality not in address.casefold():
                    continue
                # Place names that explicitly identify an office or booking desk
                # are not useful as visitable activities, even if Google assigns
                # a broad tourist_attraction type to the listing.
                normalized_name = name.casefold()
                office_terms = (
                    " office", "booking office", "ticket office", "reservation office",
                    "head office", "corporate office",
                )
                if any(term in normalized_name for term in office_terms):
                    continue
                if place_id and place_id in seen_ids:
                    continue

                item_types = set(place.get("types") or [])
                primary_type = place.get("primaryType")
                if primary_type:
                    item_types.add(primary_type)

                # Treat Google's primary type as the strongest classification
                # signal. A listing whose primary type is an agency/service/pet
                # care office should not become an activity merely because a
                # secondary type overlaps with an attraction category.
                non_activity_primary_types = agency_types | {
                    "service", "pet_care", "veterinary_care", "association_or_organization",
                    "establishment",
                }
                primary_is_non_activity = primary_type in non_activity_primary_types
                if primary_is_non_activity:
                    continue

                # Also reject generic agency listings unless they have a concrete
                # primary attraction/activity type. This keeps genuine adventure
                # sports centres while filtering booking offices.
                concrete_primary_types = concrete_activity_types - {
                    "food", "tourist_attraction", "park", "garden", "hiking_area"
                }
                if item_types & agency_types and primary_type not in concrete_primary_types:
                    continue

                # A result should match the category query that returned it.
                # This prevents unrelated businesses from being labelled as
                # nature/adventure solely because of the search query.
                expected_types = category_types.get(interest, set())
                if expected_types and not item_types & expected_types:
                    continue

                if place_id:
                    seen_ids.add(place_id)

                # Prefer the intent that produced the result. Google place types
                # are useful for correcting obvious mismatches, but can overlap.
                type_category = None
                if item_types & food_types:
                    type_category = "food"
                elif item_types & adventure_types:
                    type_category = "adventure"
                elif item_types & nature_types:
                    type_category = "nature"
                elif item_types & culture_types:
                    type_category = "culture"

                inferred_category = type_category or interest
                # Avoid assigning an unrelated type over the requested category
                # for generic Google types such as tourist_attraction or park.
                if interest in interests and (
                    (interest == "nature" and item_types & nature_types)
                    or (interest == "adventure" and item_types & adventure_types)
                    or (interest == "food" and item_types & food_types)
                    or (interest == "culture" and item_types & culture_types)
                ):
                    inferred_category = interest

                editorial = (place.get("editorialSummary") or {}).get("text")
                place_location = place.get("location") or {}
                place_lat = place_location.get("latitude")
                place_lng = place_location.get("longitude")
                distance_km = None
                if (
                    destination_center is not None
                    and isinstance(place_lat, (int, float))
                    and isinstance(place_lng, (int, float))
                ):
                    distance_km = round(
                        haversine_km(
                            destination_center[0], destination_center[1],
                            float(place_lat), float(place_lng),
                        ),
                        1,
                    )

                results.append({
                    "name": name,
                    "category": inferred_category,
                    "estimated_cost": None,
                    "duration_hours": 2.0,
                    "description": editorial or (
                        "Google Places result. Verify access, opening hours and current fees before visiting."
                    ),
                    "currency": "INR",
                    "cost_basis": "not_provided_by_google_places",
                    "is_live_price": False,
                    "price_note": "Google Places does not provide a reliable attraction ticket price in this result.",
                    "source": "Google Places API (New)",
                    "place_id": place_id,
                    "address": address,
                    "google_maps_url": place.get("googleMapsUri"),
                    "rating": place.get("rating"),
                    "user_rating_count": place.get("userRatingCount") or 0,
                    "types": sorted(item_types),
                    "primary_type": primary_type,
                    "matched_interest": interest,
                    "distance_from_destination_center_km": distance_km,
                    "distance_basis": (
                        f"straight_line_from_destination_center:{distance_center_source}"
                        if distance_km is not None else "unavailable"
                    ),
                })

            page_token = payload.get("nextPageToken")
            if not page_token:
                break

    if not results:
        return []

    # Keep ordinary city recommendations practical. Override the default with
    # TRIPWISE_MAX_ACTIVITY_DISTANCE_KM when a trip intentionally includes excursions.
    try:
        max_distance_km = max(1.0, float(os.getenv("TRIPWISE_MAX_ACTIVITY_DISTANCE_KM", "20")))
    except (TypeError, ValueError):
        max_distance_km = 20.0

    # Filter only when distance is known; do not discard otherwise valid results
    # merely because Google did not return coordinates for a particular place.
    results = [
        item for item in results
        if item.get("distance_from_destination_center_km") is None
        or item["distance_from_destination_center_km"] <= max_distance_km
    ]
    if not results:
        return []

    # Bayesian weighted rating: places with very few reviews are pulled toward
    # the candidate-pool average, preventing 5.0 from 2 reviews beating 4.7
    # from hundreds of reviews solely because of its raw star rating.
    rated = [item for item in results if isinstance(item.get("rating"), (int, float))]
    baseline = (
        sum(float(item["rating"]) for item in rated) / len(rated)
        if rated else 4.0
    )
    confidence_reviews = 50
    for item in results:
        rating = item.get("rating")
        count = int(item.get("user_rating_count") or 0)
        if isinstance(rating, (int, float)):
            item["weighted_rating"] = round(
                (count / (count + confidence_reviews)) * float(rating)
                + (confidence_reviews / (count + confidence_reviews)) * baseline,
                3,
            )
        else:
            item["weighted_rating"] = None

        # Proximity-adjusted score: distance has a meaningful but bounded effect,
        # while ratings and review volume remain important ranking signals.
        distance_km = item.get("distance_from_destination_center_km")
        if isinstance(item.get("weighted_rating"), (int, float)):
            distance_penalty = min(0.6, max(0.0, float(distance_km) * 0.015)) if distance_km is not None else 0.0
            item["proximity_adjusted_score"] = round(item["weighted_rating"] - distance_penalty, 3)
        else:
            item["proximity_adjusted_score"] = None

        # Transparent confidence labels help users interpret rating volume.
        if count >= 1000:
            item["review_confidence"] = "very_high"
            item["review_confidence_label"] = "1,000+ reviews"
        elif count >= 500:
            item["review_confidence"] = "high"
            item["review_confidence_label"] = "500–999 reviews"
        elif count >= 100:
            item["review_confidence"] = "good"
            item["review_confidence_label"] = "100–499 reviews"
        elif count >= 25:
            item["review_confidence"] = "moderate"
            item["review_confidence_label"] = "25–99 reviews"
        elif count > 0:
            item["review_confidence"] = "limited"
            item["review_confidence_label"] = "Fewer than 25 reviews"
        else:
            item["review_confidence"] = "unrated"
            item["review_confidence_label"] = "No review count available"

    # Rank within each interest first, then interleave categories so one query
    # cannot crowd out the others. Each category's strongest reviewed places lead.
    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        buckets.setdefault(item["matched_interest"], []).append(item)

    for bucket in buckets.values():
        bucket.sort(
            key=lambda item: (
                item.get("proximity_adjusted_score") is None,
                -(item.get("proximity_adjusted_score") if item.get("proximity_adjusted_score") is not None else 0),
                -int(item.get("user_rating_count") or 0),
                (
                    item["distance_from_destination_center_km"]
                    if item.get("distance_from_destination_center_km") is not None
                    else float("inf")
                ),
                item["name"].casefold(),
            )
        )
        for rank, item in enumerate(bucket):
            item["interest_rank"] = rank

    ranked: list[dict[str, Any]] = []
    max_length = max((len(bucket) for bucket in buckets.values()), default=0)
    for index in range(max_length):
        for interest in selected:
            bucket = buckets.get(interest, [])
            if index < len(bucket):
                ranked.append(bucket[index])

    return ranked


def recommend_destination_activities(
    *,
    destination: str,
    interests: list[str] | None = None,
    budget_per_person: float | None = None,
    limit: int = 12,
) -> dict[str, Any]:
    """Return curated activity ideas for supported destinations.

    Costs are indicative INR estimates per person, not live prices. For unknown
    destinations, return honest category-based ideas rather than inventing named
    attractions.
    """
    if not isinstance(destination, str) or not destination.strip():
        raise ValueError("Destination is required.")
    if budget_per_person is not None and budget_per_person < 0:
        raise ValueError("Budget per person cannot be negative.")
    if not 1 <= limit <= 30:
        raise ValueError("Limit must be between 1 and 30.")

    normalized_destination = destination.strip().casefold()
    matched_key = next(
        (key for key in _DESTINATION_ACTIVITIES if key in normalized_destination),
        None,
    )
    requested = {
        str(value).strip().casefold()
        for value in (interests or [])
        if str(value).strip()
    }
    allowed = {"adventure", "food", "nature", "culture"}
    requested &= allowed

    # Prefer real, destination-specific Google Places results when configured.
    # Google Places does not supply ticket prices reliably, so those are left unknown.
    google_candidates = _google_places_activities(destination.strip(), requested, limit)
    if google_candidates:
        candidates = google_candidates
        source = "google_places_api"
    elif matched_key:
        candidates = [dict(item) for item in _DESTINATION_ACTIVITIES[matched_key]]
        source = "curated_destination_catalogue_fallback"
    else:
        candidates = [
            {"name": "Explore a free public park or garden", "category": "nature",
             "estimated_cost": 0, "duration_hours": 1.5,
             "description": "A low-cost nature option; choose a verified local park."},
            {"name": "Visit a local museum or heritage site", "category": "culture",
             "estimated_cost": 250, "duration_hours": 2.0,
             "description": "Choose a real local venue and verify its opening hours and entry fee."},
            {"name": "Try a local food market or regional dish", "category": "food",
             "estimated_cost": 400, "duration_hours": 1.5,
             "description": "Choose a well-reviewed local market or eatery."},
            {"name": "Book a guided outdoor activity", "category": "adventure",
             "estimated_cost": 1000, "duration_hours": 2.5,
             "description": "Verify the operator, availability and safety conditions before booking."},
        ]
        source = "category_fallback_needs_local_verification"

    if requested:
        prioritized = [item for item in candidates if item["category"] in requested]
        other = [item for item in candidates if item["category"] not in requested]
        candidates = prioritized + other

    for item in candidates:
        item["currency"] = "INR"
        if source != "google_places_api":
            item["cost_basis"] = "estimated_per_person"
        item["is_live_price"] = False
        if budget_per_person is not None and item.get("estimated_cost") is not None:
            item["fits_activity_budget"] = item["estimated_cost"] <= budget_per_person
        elif budget_per_person is not None:
            item["fits_activity_budget"] = None
            item["budget_status"] = "unknown_price"
        if item.get("estimated_cost") is None:
            item.setdefault("budget_status", "unknown_price")
        else:
            item.setdefault("budget_status", "estimated")

    candidates.sort(
        key=lambda item: (
            0 if not requested or item["category"] in requested else 1,
            0 if item.get("fits_activity_budget") is True else
            1 if item.get("fits_activity_budget") is None else 2,
            item.get("interest_rank", 0),
            item["estimated_cost"] if item.get("estimated_cost") is not None else float("inf"),
            -(item.get("weighted_rating") or 0),
            -int(item.get("user_rating_count") or 0),
            item["name"].casefold(),
        )
    )
    return {
        "destination": destination.strip(),
        "matched_destination": matched_key,
        "interests_applied": sorted(requested),
        "source": source,
        "price_note": (
            "Google Places does not provide reliable attraction ticket prices; verify fees before visiting."
            if source == "google_places_api"
            else "Indicative estimates per person in INR; verify current fees, opening hours and availability."
        ),
        "ranking_note": (
            "Google Places results are filtered to addresses containing the requested locality, deduplicated, "
            "and normally limited to 20 km from the destination centre when distance is available. Ranking uses "
            "Bayesian-style weighted ratings adjusted modestly for proximity, with review count as a tie-breaker. "
            "Set TRIPWISE_MAX_ACTIVITY_DISTANCE_KM to change the default radius. Distances are straight-line estimates; "
            "Google may still omit relevant places or format locality names differently."
            if source == "google_places_api"
            else "Curated or fallback recommendations; Google review ranking is unavailable."
        ),
        "activities": candidates[:limit],
    }
