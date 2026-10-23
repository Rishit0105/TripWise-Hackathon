from datetime import datetime
from flight_scraper import FlightScraper
from buses import get_live_buses
import re


AIRPORT_CODES = {
    "delhi": "DEL",
    "new delhi": "DEL",
    "mumbai": "BOM",
    "bombay": "BOM",
    "bangalore": "BLR",
    "bengaluru": "BLR",
    "chennai": "MAA",
    "kolkata": "CCU",
    "hyderabad": "HYD",
    "pune": "PNQ",
    "ahmedabad": "AMD",
    "jaipur": "JAI",
    "lucknow": "LKO",
    "chandigarh": "IXC",
    "amritsar": "ATQ",
    "udaipur": "UDR",
    "jodhpur": "JDH",
    "goa": "GOI",
    "bhuntar": "KUU",
    "kullu": "KUU",
    "kullu manali airport": "KUU",
    "manali": "KUU",  # Manali is served most directly by Bhuntar Airport.
}

# Google Flights should search the airport-served city, not the destination label.
FLIGHT_SEARCH_CITIES = {
    "manali": "Bhuntar Airport",
    "kullu": "Bhuntar Airport",
    "kullu manali": "Bhuntar Airport",
    "bhuntar": "Bhuntar Airport",
}

FLIGHT_DESTINATION_NOTES = {
    "manali": "Manali has no airport. This search targets Bhuntar (KUU); onward ground transport to Manali is required.",
    "kullu": "This search targets Bhuntar (KUU). Verify onward ground transport.",
}


def get_airport_code(location):
    """
    Convert a city/location name into an IATA airport code.

    Returns None if the city is not currently supported.
    """

    if not location:
        return None

    location_clean = location.strip().lower()

    return AIRPORT_CODES.get(location_clean)


def _extract_iata_route(duration_text):
    """Extract an origin/destination IATA pair from scraper route text."""
    text = str(duration_text or "").upper().replace("–", "-").replace("—", "-")
    # Google Flights commonly includes a route such as "DEL–IXC" in duration text.
    match = re.search(r"\b([A-Z]{3})\s*[-/]\s*([A-Z]{3})\b", text)
    return (match.group(1), match.group(2)) if match else (None, None)


def _parse_clock_time(value):
    """Parse the first 12-hour or 24-hour clock time from scraped text."""
    text = str(value or "").replace("\u202f", " ").replace("\xa0", " ")
    match = re.search(r"(?i)(\d{1,2}:\d{2}\s*(?:AM|PM)?)", text)
    if not match:
        return None
    token = re.sub(r"\s+", " ", match.group(1).strip()).upper()
    for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M"):
        try:
            return datetime.strptime(token, fmt).time()
        except ValueError:
            continue
    return None


def _normalized_flight_times(flight):
    """Return separate HH:MM flight departure and arrival strings when parseable."""
    departure_value = str(flight.get("departure") or flight.get("departure_time") or "")
    arrival_value = str(flight.get("arrival") or flight.get("arrival_time") or "")

    # Google Flights sometimes places both clock times in the departure field.
    combined_text = " ".join((departure_value, arrival_value))
    combined_text = (combined_text.replace("\u202f", " ")
                     .replace("\xa0", " ")
                     .replace("\u2009", " "))
    pattern = r"(?i)(\d{1,2}:\d{2}\s*(?:AM|PM))"
    times = re.findall(pattern, combined_text)

    if len(times) >= 2 and not arrival_value.strip():
        departure_time = _parse_clock_time(times[0])
        arrival_time = _parse_clock_time(times[1])
    else:
        departure_time = _parse_clock_time(departure_value)
        arrival_time = _parse_clock_time(arrival_value)
        if arrival_time is None and len(times) >= 2:
            departure_time = _parse_clock_time(times[0])
            arrival_time = _parse_clock_time(times[1])

    return (
        departure_time.strftime("%H:%M") if departure_time else "",
        arrival_time.strftime("%H:%M") if arrival_time else "",
    )


def _bus_leg_datetimes(bus, travel_date):
    """Return bus departure/arrival datetimes, accounting for overnight travel."""
    from datetime import timedelta
    try:
        day = datetime.strptime(travel_date, "%d/%m/%Y").date()
    except (TypeError, ValueError):
        return None, None
    departure_time = _parse_clock_time(bus.get("departure_time"))
    arrival_time = _parse_clock_time(bus.get("arrival_time"))
    if not departure_time or not arrival_time:
        return None, None
    departure = datetime.combine(day, departure_time)
    arrival = datetime.combine(day, arrival_time)
    if arrival <= departure:
        arrival += timedelta(days=1)
    return departure, arrival


def _flight_leg_datetimes(flight, travel_date):
    """Return flight departure/arrival datetimes only when both times are parseable."""
    from datetime import timedelta

    try:
        day = datetime.strptime(travel_date, "%d/%m/%Y").date()
    except (TypeError, ValueError):
        return None, None

    departure_value = str(flight.get("departure_time") or "")
    arrival_value = str(flight.get("arrival_time") or "")

    # Normalize Google's narrow/non-breaking spaces before parsing.
    departure_value = (
        departure_value.replace("\u202f", " ")
        .replace("\xa0", " ")
        .replace("\u2009", " ")
    )
    arrival_value = (
        arrival_value.replace("\u202f", " ")
        .replace("\xa0", " ")
        .replace("\u2009", " ")
    )

    departure_time = _parse_clock_time(departure_value)
    arrival_time = _parse_clock_time(arrival_value)

    # Some Google Flights cards expose both times in one string, e.g.
    # "9:10 PM – 10:20 PM", and leave the separate arrival field empty.
    if not arrival_time:
        time_pattern = r"(?i)(\d{1,2}:\d{2}\s*(?:AM|PM))"
        times = re.findall(time_pattern, departure_value)
        if len(times) >= 2:
            departure_time = _parse_clock_time(times[0])
            arrival_time = _parse_clock_time(times[1])

    # Fail closed: never infer a schedule from duration alone.
    if departure_time is None or arrival_time is None:
        return None, None

    departure = datetime.combine(day, departure_time)
    arrival = datetime.combine(day, arrival_time)
    if arrival <= departure:
        arrival += timedelta(days=1)

    return departure, arrival


def _connection_is_feasible(first_leg, second_leg, travel_date, minimum_buffer_hours=3):
    """
    Validate a bus/flight transfer conservatively.

    Returns False if either leg's schedule is missing/unparseable. A minimum
    three-hour buffer is required between arrival at the hub and departure.
    """
    from datetime import timedelta

    first_mode = str(first_leg.get("mode") or "").strip().lower()
    second_mode = str(second_leg.get("mode") or "").strip().lower()

    if first_mode == "bus" and second_mode == "flight":
        _, first_arrival = _bus_leg_datetimes(first_leg, travel_date)
        second_departure, _ = _flight_leg_datetimes(second_leg, travel_date)
    elif first_mode == "flight" and second_mode == "bus":
        _, first_arrival = _flight_leg_datetimes(first_leg, travel_date)
        second_departure, _ = _bus_leg_datetimes(second_leg, travel_date)
    else:
        return False

    if first_arrival is None or second_departure is None:
        return False

    return second_departure >= first_arrival + timedelta(hours=minimum_buffer_hours)


def _expected_flight_codes(location):
    """Return the expected airport code for a supported city/location."""
    return get_airport_code(location)


def _convert_duration_to_hours(duration_seconds):
    """
    Convert flight duration from seconds to hours.
    """

    if duration_seconds is None:
        return None

    return round(duration_seconds / 3600, 2)


def _get_flight_options(
    starting_location,
    destination,
    travel_date,
    travellers
):
    """
    Retrieve live flights for the requested route.

    For Manali/Kullu, try Bhuntar (KUU) first. If no direct results are
    returned, search Chandigarh (IXC) as a clearly labelled nearby-airport
    alternative. Alternative flights are never labelled as flights to KUU.
    """
    scraper = None
    try:
        if travellers <= 0:
            print("Invalid traveller count for flight search.")
            return []

        formatted_date = datetime.strptime(
            travel_date, "%d/%m/%Y"
        ).strftime("%Y-%m-%d")

        origin_code = get_airport_code(starting_location)
        destination_code = get_airport_code(destination)

        if not origin_code or not destination_code:
            print("Unsupported airport for flight search.")
            return []

        destination_key = destination.strip().lower()
        is_mountain_destination = destination_key in {
            "manali", "kullu", "kullu manali", "kullu manali airport", "bhuntar"
        }

        scraper = FlightScraper()
        search_targets = [
            {
                "code": destination_code,
                "label": destination,
                "is_alternative": False,
            }
        ]

        # Only attempt a nearby airport if the requested Kullu/Manali route
        # returns no results. This is an alternative route, not a KUU flight.
        if is_mountain_destination and destination_code == "KUU":
            search_targets.append({
                "code": "IXC",
                "label": "Chandigarh (IXC) — alternative airport for Manali",
                "is_alternative": True,
            })

        for target in search_targets:
            print(
                f"Searching flight route {origin_code} to {target['code']} "
                f"for {formatted_date}"
            )
            flights = scraper.search_flights(
                source=origin_code,
                destination=target["code"],
                date=formatted_date
            )

            if not flights:
                continue

            flight_options = []
            rejected_route_count = 0

            for flight in flights[:10]:
                duration_text = str(flight.get("duration", "") or "")
                actual_origin_code, actual_destination_code = _extract_iata_route(
                    duration_text
                )

                # Fail closed: a flight is only shown as a valid option when
                # its scraped airport pair explicitly matches the searched route.
                # This avoids labelling unrelated or unverified results as valid.
                route_codes_known = bool(actual_origin_code and actual_destination_code)
                route_matches = (
                    route_codes_known
                    and actual_origin_code == origin_code
                    and actual_destination_code == target["code"]
                )

                if not route_matches:
                    rejected_route_count += 1
                    continue

                price_text = str(flight.get("price", "") or "")
                price_match = re.search(r"[\d,]+", price_text)
                if not price_match:
                    continue

                displayed_price = int(price_match.group().replace(",", ""))
                fare_type = str(flight.get("fare_type", "unknown")).lower()
                # Only expose a numeric fare as a comparable price when the
                # scraper explicitly identifies it as one-way.
                price_is_one_way = fare_type == "one_way"
                price_per_person = displayed_price if price_is_one_way else None

                duration_hours = 0.0
                duration_match = re.search(r"(\d+)\s*hr", duration_text)
                minutes_match = re.search(r"(\d+)\s*min", duration_text)
                if duration_match:
                    duration_hours += int(duration_match.group(1))
                if minutes_match:
                    duration_hours += round(int(minutes_match.group(1)) / 60, 2)

                normalized_departure, normalized_arrival = _normalized_flight_times(flight)

                is_alternative = target["is_alternative"]
                route_label = (
                    f"{starting_location} to Chandigarh (IXC), then ground transport to {destination}"
                    if is_alternative
                    else f"{starting_location} to Bhuntar (KUU)"
                    if is_mountain_destination
                    else f"{starting_location} to {destination}"
                )

                flight_options.append({
                    "mode": "Flight",
                    "provider": flight.get("airline", "Unknown Airline"),
                    "flight_number": flight.get("flight_number", ""),
                    "duration_hours": duration_hours,
                    "duration": duration_text,
                    "price_per_person": price_per_person,
                    "total_price": price_per_person * travellers if price_per_person is not None else None,
                    "displayed_price": displayed_price,
                    "fare_type": fare_type,
                    "fare_type_note": flight.get(
                        "fare_type_note",
                        "Fare type unverified; do not treat this as a confirmed one-way fare."
                    ),
                    "currency": "INR",
                    "price_type": "Live" if price_is_one_way else "Unverified fare type",
                    "comfort_level": "High",
                    "booking_required": True,
                    "distance_km": None,
                    "route": route_label,
                    "requested_origin": starting_location,
                    "requested_destination": destination,
                    "origin_airport_code": origin_code,
                    "destination_airport_code": target["code"],
                    "scraped_origin_airport_code": actual_origin_code,
                    "scraped_destination_airport_code": actual_destination_code,
                    "route_verified": route_matches,
                    "is_nearby_airport_alternative": is_alternative,
                    "onward_ground_transport_required": is_mountain_destination,
                    "routing_note": (
                        "Alternative airport: flight lands at Chandigarh (IXC), not Bhuntar (KUU). "
                        f"Arrange and price ground transport from Chandigarh to {destination} separately."
                        if is_alternative
                        else FLIGHT_DESTINATION_NOTES.get(destination_key)
                    ),
                    "departure_time": normalized_departure,
                    "arrival_time": normalized_arrival,
                    "stops": flight.get("stops", "Nonstop"),
                    "booking_link": "https://www.google.com/travel/flights",
                    "price_level": None,
                })

            if rejected_route_count:
                print(
                    f"Rejected {rejected_route_count} flight result(s) for "
                    f"requested route {origin_code} to {target['code']}."
                )

            if flight_options:
                return flight_options

        print("\\nNo verified live flights found for the requested route or configured nearby-airport fallback.")
        return []

    except Exception as error:
        print(f"\\nFlight scraper unavailable: {error}")
        return []
    finally:
        if scraper:
            scraper.close()


def _get_bus_options(
        starting_location,
        destination,
        travel_date,
        travellers
):
    try:
        return get_live_buses(
            starting_location,
            destination,
            travel_date,
            travellers
        )

    except Exception as error:
        print(f"\nLive Bus API unavailable: {error}")

        return []


def calculate_approximate_price(options, travellers):
    if not options:
        return None

    prices = []

    for option in options:
        price = option.get("price_per_person")

        if price is not None:
            prices.append(price)

    if not prices:
        return None

    prices.sort()

    middle = len(prices) // 2

    if len(prices) % 2 == 0:
        approximate_price = (
            prices[middle - 1] + prices[middle]
        ) / 2

    else:
        approximate_price = prices[middle]

    return round(approximate_price)


def _get_estimated_train_options(
        starting_location,
        destination,
        travellers,
        distance_km,
        duration_hours
):
    train_price_per_person =   max(250, round(distance_km * 1.8))

    train_duration = max(1, round(duration_hours * 1.10, 1))

    return [
        {
            "mode": "Train",
            "provider": "Estimated Train Service",
            "duration_hours": train_duration,
            "price_per_person": train_price_per_person,
            "total_price": train_price_per_person * travellers,
            "currency": "INR",
            "price_type": "Estimated",
            "comfort_level": "High",
            "booking_required": True,
            "distance_km": distance_km,
            "route": f"{starting_location} to {destination}"
        }
    ]


def _get_estimated_cab_options(
        starting_location,
        destination,
        travellers,
        distance_km,
        duration_hours
):
    cab_total_price = max(1200, round(distance_km * 12))

    cab_duration = max(1 , round(duration_hours, 1))

    return [
        {
            "mode": "Cab",
            "provider": "Estimated Cab Service",
            "duration_hours": cab_duration,
            "price_per_person": round(
                cab_total_price / travellers
            ),
            "total_price": cab_total_price,
            "currency": "INR",
            "price_type": "Estimated",
            "comfort_level": "High",
            "booking_required": True,
            "distance_km": distance_km,
            "route": f"{starting_location} to {destination}"
        }
    ]


def get_transport_estimates(
        starting_location,
        destination,
        travel_date,
        travellers,
        route_information = None
):
    if travellers <= 0:
        raise ValueError(
            "Number of travellers must be greater than 0."
        )

    if not travel_date.strip():
        raise ValueError(
            "Travel date cannot be empty."
        )

    if not starting_location.strip():
        raise ValueError(
            "Starting Location cannot be empty."
        )

    if not destination.strip():
        raise ValueError(
            "Destination cannot be empty."
        )

    if not route_information:
        raise ValueError(
            "Route information is required for transport estimation."
        )

    distance_km = route_information.get("distance_km")
    duration_hours = route_information.get("duration_hours")

    if not distance_km or distance_km <= 0:
        raise ValueError(
            "Valid route distance is required for transport estimation."
        )

    if not duration_hours or duration_hours <= 0:
        duration_hours = distance_km / 60

    train_options = _get_estimated_train_options(
        starting_location,
        destination,
        travellers,
        distance_km,
        duration_hours
    )

    cab_options = _get_estimated_cab_options(
        starting_location,
        destination,
        travellers,
        distance_km,
        duration_hours
    )

    bus_options = _get_bus_options(
        starting_location,
        destination,
        travel_date,
        travellers
    )

    if not bus_options:
        bus_price_per_person = max(
            300,
            round(distance_km * 2.5)
        )

        bus_duration = max(
            1,
            round(duration_hours * 1.25, 1)
        )

        bus_options = [
            {
                "mode": "Bus",
                "provider": "Estimated Bus Service",
                "duration_hours": bus_duration,
                "price_per_person": bus_price_per_person,
                "total_price": (
                    bus_price_per_person * travellers
                ),
                "currency": "INR",
                "price_type": "Estimated",
                "comfort_level": "Medium",
                "booking_required": True,
                "distance_km": distance_km,
                "route": (
                    f"{starting_location} to "
                    f"{destination}"
                )
            }
        ]

    flight_options = _get_flight_options(
        starting_location,
        destination,
        travel_date,
        travellers
    )

    if not flight_options:
        flight_options = []

    estimates = {}

    estimates["Bus"] = {
        "approx_price": calculate_approximate_price(
            bus_options,
            travellers
            ),
        "price_type": (
            "Live"
            if any(
                option.get("price_type") == "Live"
                for option in bus_options
            )
            else "Estimated"
        )
    }

    estimates["Train"] = {
        "approx_price": calculate_approximate_price(
            train_options,
            travellers
        ),
        "price_type": "Estimated"
    }

    estimates["Cab"] = {
        "approx_price": calculate_approximate_price(
            cab_options,
            travellers
        ),
        "price_type": "Estimated"
    }

    estimates["Flight"] = {
        "approx_price": calculate_approximate_price(
            flight_options,
            travellers
        ),
        "price_type": (
            "Live"
            if any(
                option.get("price_type") == "Live"
                and option.get("price_per_person") is not None
                for option in flight_options
            )
            else "Unverified fare"
            if flight_options
            else "Unavailable"
        )
    }

    return estimates


def get_transport_options(
    mode,
    starting_location,
    destination,
    travel_date,
    travellers,
    route_information=None
):
    if travellers <= 0:
        raise ValueError(
            "Number of travellers must be greater than zero."
        )

    if not travel_date.strip():
        raise ValueError(
            "Travel date cannot be empty."
        )

    if not starting_location.strip():
        raise ValueError(
            "Starting location cannot be empty."
        )

    if not destination.strip():
        raise ValueError(
            "Destination cannot be empty."
        )

    distance_km = None
    duration_hours = None

    if route_information:
        distance_km = route_information.get(
            "distance_km"
        )

        duration_hours = route_information.get(
            "duration_hours"
        )

    if not distance_km or distance_km <= 0:
        raise ValueError(
            "Valid route distance is required "
            "for transport estimation."
        )

    if not duration_hours or duration_hours <= 0:
        duration_hours = distance_km / 60

    mode = mode.strip().lower()

    if mode == "flight":
        return _get_flight_options(
            starting_location,
            destination,
            travel_date,
            travellers
        )

    elif mode == "bus":
        bus_options = _get_bus_options(
            starting_location,
            destination,
            travel_date,
            travellers
        )

        if bus_options:
            return bus_options

        # Fallback to estimated bus
        bus_price_per_person = max(
            300,
            round(distance_km * 2.5)
        )

        bus_duration = max(
            1,
            round(duration_hours * 1.25, 1)
        )

        return [
            {
                "mode": "Bus",
                "provider": "Estimated Bus Service",
                "duration_hours": bus_duration,
                "price_per_person": bus_price_per_person,
                "total_price": (
                    bus_price_per_person * travellers
                ),
                "currency": "INR",
                "price_type": "Estimated",
                "comfort_level": "Medium",
                "booking_required": True,
                "distance_km": distance_km,
                "route": (
                    f"{starting_location} to "
                    f"{destination}"
                )
            }
        ]

    elif mode == "train":
        return _get_estimated_train_options(
            starting_location,
            destination,
            travellers,
            distance_km,
            duration_hours
        )

    elif mode == "cab":
        return _get_estimated_cab_options(
            starting_location,
            destination,
            travellers,
            distance_km,
            duration_hours
        )

    else:
        raise ValueError(
            f"Unsupported transport mode: {mode}"
        )
    

# Nearby ground hubs used to build complete multimodal alternatives.
# Keep this mapping data-driven so additional cities can be added without
# changing route-combination logic. These are candidate hubs, not guarantees
# of service; every bus/flight leg is searched live before it is returned.
NEARBY_GROUND_HUBS = {
    "manali": ["Chandigarh"],
    "kullu": ["Chandigarh"],
    "kullu manali": ["Chandigarh"],
    "bhuntar": ["Chandigarh"],
    "shimla": ["Chandigarh"],
    "dharamshala": ["Chandigarh"],
    "jibhi": ["Chandigarh"],
    "rishikesh": ["Dehradun", "Delhi"],
    "mussoorie": ["Dehradun", "Delhi"],
    "agra": ["Delhi"],
    "jaipur": ["Delhi"],
    "amritsar": ["Chandigarh", "Delhi"],
    "chandigarh": ["Delhi"],
}

def _location_key(location):
    return re.sub(r"\s+", " ", str(location or "").strip().lower())


def _safe_duration_hours(option):
    """Return a numeric duration only when the option provides one."""
    value = option.get("duration_hours")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _combine_legs(label, legs, travellers, route_note):
    """Create a selectable itinerary from individually searched transport legs."""
    total_price = 0
    all_prices_known = True
    total_duration = 0.0
    all_durations_known = True
    price_types = []
    for leg in legs:
        price = leg.get("total_price")
        if price is None:
            all_prices_known = False
        else:
            try:
                total_price += float(price)
            except (TypeError, ValueError):
                all_prices_known = False
        duration = _safe_duration_hours(leg)
        if duration is None:
            all_durations_known = False
        else:
            total_duration += duration
        price_types.append(leg.get("price_type", "Unknown"))

    return {
        "mode": "Multimodal",
        "provider": label,
        "route": " → ".join(str(leg.get("route", "")) for leg in legs),
        "legs": legs,
        "leg_count": len(legs),
        "travellers": travellers,
        "total_price": round(total_price) if all_prices_known else None,
        "price_per_person": round(total_price / travellers) if all_prices_known and travellers else None,
        "currency": "INR",
        "price_type": "Live" if all(t == "Live" for t in price_types) else "Mixed/Estimated",
        "duration_hours": round(total_duration, 2) if all_durations_known else None,
        "booking_required": True,
        "is_complete_itinerary": True,
        "routing_note": route_note,
        "booking_links": [leg.get("booking_link") for leg in legs if leg.get("booking_link")],
    }


def get_multimodal_route_options(
    starting_location,
    destination,
    travel_date,
    travellers=1,
    include_direct_bus=True,
):
    """
    Return complete, selectable route alternatives using live leg searches.

    Example: Manali -> Delhi may return (when live searches confirm both legs)
    1) direct bus Manali -> Delhi
    2) bus Manali -> Chandigarh + flight Chandigarh -> Delhi

    Add more entries to NEARBY_GROUND_HUBS to support more regions. No
    combined itinerary is returned unless each constituent live leg exists.
    """
    if travellers <= 0:
        raise ValueError("Number of travellers must be greater than zero.")
    if not str(starting_location or "").strip() or not str(destination or "").strip():
        raise ValueError("Starting location and destination are required.")
    datetime.strptime(travel_date, "%d/%m/%Y")

    origin = str(starting_location).strip()
    target = str(destination).strip()
    origin_key = _location_key(origin)
    target_key = _location_key(target)
    options = []
    seen = set()

    # Direct bus is always searched so a fallback flight never hides a simpler route.
    if include_direct_bus:
        direct_buses = _get_bus_options(origin, target, travel_date, travellers)
        for bus in direct_buses[:5]:
            options.append(_combine_legs(
                "Direct bus",
                [bus],
                travellers,
                "Direct bus option. Verify departure and arrival details before booking."
            ))

    # Pattern A: origin is near a hub, so travel by ground to the hub, then fly.
    for hub in NEARBY_GROUND_HUBS.get(origin_key, []):
        ground_legs = _get_bus_options(origin, hub, travel_date, travellers)
        if not ground_legs:
            continue
        flight_legs = _get_flight_options(hub, target, travel_date, travellers)
        if not flight_legs:
            continue
        for bus in ground_legs[:3]:
            for flight in flight_legs[:3]:
                if not _connection_is_feasible(bus, flight, travel_date):
                    print(
                        f"Skipping infeasible or unverified connection: "
                        f"{bus.get('route')} -> {flight.get('route')} "
                        f"(bus arrival={bus.get('arrival_time')!r}, "
                        f"flight schedule={flight.get('departure_time')!r} / "
                        f"{flight.get('arrival_time')!r})"
                    )
                    continue
                options.append(_combine_legs(
                    f"Bus via {hub} + flight",
                    [bus, flight],
                    travellers,
                    f"Ground transfer to {hub}, then flight to {target}. Check flight fare type and leave sufficient transfer time."
                ))

    # Pattern B: destination is near a hub, so fly to the hub then travel by ground.
    for hub in NEARBY_GROUND_HUBS.get(target_key, []):
        flight_legs = _get_flight_options(origin, hub, travel_date, travellers)
        if not flight_legs:
            continue
        ground_legs = _get_bus_options(hub, target, travel_date, travellers)
        if not ground_legs:
            continue
        for flight in flight_legs[:3]:
            for bus in ground_legs[:3]:
                if not _connection_is_feasible(flight, bus, travel_date):
                    print(
                        f"Skipping infeasible or unverified connection: "
                        f"{flight.get('route')} -> {bus.get('route')} "
                        f"(flight schedule={flight.get('departure_time')!r} / "
                        f"{flight.get('arrival_time')!r}, "
                        f"bus departure={bus.get('departure_time')!r})"
                    )
                    continue
                options.append(_combine_legs(
                    f"Flight via {hub} + bus",
                    [flight, bus],
                    travellers,
                    f"Flight to {hub}, then ground transfer to {target}. Check flight fare type and allow enough transfer time."
                ))

    # Deduplicate identical leg sequences, preserving order.
    deduped = []
    for option in options:
        key = tuple(
            (leg.get("mode"), leg.get("route"), leg.get("provider"))
            for leg in option.get("legs", [])
        )
        if key not in seen:
            seen.add(key)
            deduped.append(option)

    # Put fully live, priced options first, then cheaper options when price is known.
    deduped.sort(key=lambda item: (
        item.get("total_price") is None,
        item.get("price_type") != "Live",
        item.get("total_price") if item.get("total_price") is not None else float("inf"),
    ))
    return deduped

if __name__ == "__main__":
    test_route = {
        "distance_km": 303.51,
        "duration_hours": 4.55
    }

    estimates = get_transport_estimates(
        starting_location="Delhi",
        destination="Jaipur",
        travel_date="20/10/2026",
        travellers=1,
        route_information=test_route
    )

    print("\n" + "=" * 50)
    print("TRANSPORT PRICE ESTIMATES")
    print("=" * 50)

    for mode, data in estimates.items():
        print(
            f"{mode}: "
            f"₹{data['approx_price']:,} "
            f"({data['price_type']})"
        )
