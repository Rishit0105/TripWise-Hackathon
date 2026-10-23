import re
from datetime import datetime
from typing import Any


_DATE_PATTERNS = (
    (re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b"), ("%Y-%m-%d",)),
    (re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b"), ("%d/%m/%Y", "%m/%d/%Y")),
    (
        re.compile(
            r"\b\d{1,2}(?:st|nd|rd|th)?\s+"
            r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
            r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|"
            r"nov(?:ember)?|dec(?:ember)?)"
            r"(?:\s+\d{4})?\b",
            re.IGNORECASE,
        ),
        (
            "%d %B %Y", "%d %b %Y", "%d %B", "%d %b",
        ),
    ),
    (
        re.compile(
            r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
            r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|"
            r"nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}"
            r"(?:,?\s+\d{4})?\b",
            re.IGNORECASE,
        ),
        (
            "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y",
            "%B %d", "%b %d",
        ),
    ),
)


def _find_dates(text: str) -> tuple[list[tuple[int, int, str]], str | None]:
    """Return date spans and normalized ISO dates where the year is known."""
    found: list[tuple[int, int, str]] = []
    occupied: list[tuple[int, int]] = []

    for pattern, formats in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            if any(match.start() < end and match.end() > start for start, end in occupied):
                continue

            raw = re.sub(r"(?i)(\d)(st|nd|rd|th)\b", r"\1", match.group(0)).strip()
            parsed = None
            for fmt in formats:
                try:
                    parsed = datetime.strptime(raw, fmt)
                    break
                except ValueError:
                    continue

            # A date without a year is recognized so it won't be mistaken for a route,
            # but it remains unnormalized rather than assuming a year.
            normalized = parsed.strftime("%Y-%m-%d") if parsed and re.search(r"\b\d{4}\b", raw) else ""
            found.append((match.start(), match.end(), normalized))
            occupied.append((match.start(), match.end()))

    found.sort(key=lambda item: item[0])
    return found, None


def _date_free_text(text: str, spans: list[tuple[int, int, str]]) -> str:
    result = text
    for start, end, _ in reversed(spans):
        result = result[:start] + " " + result[end:]
    result = re.sub(r"\bfrom\s+to\b", " ", result, flags=re.IGNORECASE)
    result = re.sub(r"\s+", " ", result).strip()
    return result


def extract_trip_intent(message: str) -> dict[str, Any]:
    text = message.strip()
    lower = text.lower()

    intent: dict[str, Any] = {
        "intent": "plan_trip",
        "origin": None,
        "destination": None,
        "travelers": None,
        "trip_days": None,
        "budget": None,
        "start_date": None,
        "end_date": None,
        "transport_preferences": [],
        "stay_preferences": [],
        "needs_live_transport_prices": False,
        "needs_live_stay_prices": False,
        "missing_fields": [],
        "clarification_needed": False,
    }

    date_spans, _ = _find_dates(text)
    date_values = [value for _, _, value in date_spans if value]
    if date_values:
        intent["start_date"] = date_values[0]
        if len(date_values) > 1:
            intent["end_date"] = date_values[1]

    # Exclude recognized date strings before parsing a "from ... to ..." route.
    route_text = _date_free_text(text, date_spans)

    # Route: "from Delhi to Manali". Stop before trip constraints.
    route_match = re.search(
        r"\bfrom\s+(.+?)\s+to\s+(.+?)"
        r"(?=\s+(?:for|under|within|between|on|starting|with|by|budget)\b|[,;.]|$)",
        route_text,
        re.IGNORECASE,
    )
    if route_match:
        origin = route_match.group(1).strip(" ,")
        destination = route_match.group(2).strip(" ,")
        if origin and destination:
            intent["origin"] = origin
            intent["destination"] = destination
    else:
        # Destination-only requests: "plan a trip to Manali", "travel to Jaipur".
        destination_match = re.search(
            r"\b(?:trip|travel|vacation|holiday|journey)\s+to\s+(.+?)"
            r"(?=\s+(?:for|under|within|between|on|starting|with|by|budget|"
            r"for\s+\d+)\b|[,;.]|$)",
            route_text,
            re.IGNORECASE,
        )
        if destination_match:
            destination = destination_match.group(1).strip(" ,")
            # Remove trailing purpose phrases accidentally captured after destination.
            destination = re.split(
                r"\s+(?:for|under|within|between|on|starting|with|by|budget)\b",
                destination,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip(" ,")
            if destination:
                intent["destination"] = destination

    # Duration: "4 days", "4-day trip", "3 nights", "2 weeks".
    duration_match = re.search(
        r"\b(?:for\s+)?(\d+)\s*[- ]?\s*(days?|nights?|weeks?)\b",
        lower,
    )
    if duration_match:
        amount = int(duration_match.group(1))
        unit = duration_match.group(2)
        if unit.startswith("week"):
            amount *= 7
        elif unit.startswith("night"):
            amount += 1
        intent["trip_days"] = amount

    # Travellers: explicit counts only; avoid guessing from unrelated numbers.
    travelers_match = re.search(
        r"\b(\d+)\s*(?:people|persons|travellers|travelers|adults)\b",
        lower,
    )
    if travelers_match:
        intent["travelers"] = int(travelers_match.group(1))

    # Budget.
    budget_match = re.search(
        r"(?:₹|rs\.?|inr)\s*([\d,]+)"
        r"|\b(?:budget(?:\s+of)?|under|within|below|less than)\s+"
        r"(?:₹|rs\.?|inr)?\s*([\d,]+)",
        lower,
    )
    if budget_match:
        amount = budget_match.group(1) or budget_match.group(2)
        intent["budget"] = int(amount.replace(",", ""))

    # Transport preferences.
    transport_terms = {
        "flight": ("flight", "flights", "plane", "airfare"),
        "train": ("train", "trains", "rail"),
        "bus": ("bus", "buses", "coach"),
        "cab": ("cab", "taxi", "car"),
    }
    for mode, terms in transport_terms.items():
        if any(re.search(rf"\b{re.escape(term)}\b", lower) for term in terms):
            intent["transport_preferences"].append(mode)

    cheapest_transport = any(
        phrase in lower
        for phrase in (
            "cheapest transport",
            "cheapest way to travel",
            "compare transport",
            "compare all transport",
        )
    )
    if cheapest_transport and not intent["transport_preferences"]:
        intent["transport_preferences"] = ["flight", "train", "bus", "cab"]

    # Stay preferences.
    stay_terms = {
        "hotel": ("hotel", "hotels"),
        "airbnb": ("airbnb", "vacation rental", "holiday rental"),
        "hostel": ("hostel", "hostels"),
    }
    for stay, terms in stay_terms.items():
        if any(re.search(rf"\b{re.escape(term)}\b", lower) for term in terms):
            intent["stay_preferences"].append(stay)

    # Mark requests for price lookup without claiming that prices were fetched.
    complete_trip = bool(
        re.search(r"\bplan\b", lower)
        and re.search(r"\btrip\b", lower)
    )
    transport_price_terms = (
        "cheapest transport", "live transport prices", "current transport prices",
        "ticket prices", "flight prices", "train prices", "bus prices", "cab prices",
        "cheapest way to travel",
    )
    stay_price_terms = (
        "live hotel prices", "hotel prices", "hotel availability", "airbnb prices",
        "accommodation prices", "stay prices", "live prices",
    )
    intent["needs_live_transport_prices"] = (
        complete_trip
        or cheapest_transport
        or any(term in lower for term in transport_price_terms)
    )
    intent["needs_live_stay_prices"] = (
        complete_trip
        or any(term in lower for term in stay_price_terms)
    )

    required_fields = ("origin", "destination", "travelers", "trip_days", "budget")
    intent["missing_fields"] = [
        field for field in required_fields if intent[field] is None
    ]
    intent["clarification_needed"] = bool(intent["missing_fields"])
    return intent
