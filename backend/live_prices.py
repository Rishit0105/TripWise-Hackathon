"""Adapters for TripWise live transport and accommodation search.

Existing scraper implementations are imported/called; scraper source files are not modified.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from transportation import get_transport_options, get_live_buses  # existing project modules

BASE_DIR = Path(__file__).resolve().parent
_HOTEL_STDOUT_WRAPPER = None  # Keep wrapper alive so it cannot close the real stdout.


def _parse_price(value: Any) -> float | None:
    """Parse a displayed currency string into a numeric amount when possible."""
    if value is None:
        return None
    match = re.search(r"[\d,]+(?:\.\d{1,2})?", str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


class _SafeStdoutProxy:
    """Give legacy scraper imports a disposable buffer, never the API stdout."""
    def __init__(self) -> None:
        import io
        self.buffer = io.BytesIO()


def _load_hotels_module():
    """Import the hotel scraper without letting it wrap/close the API stdout."""
    scraper_path = BASE_DIR / "google_hotels_scraper.py"
    if not scraper_path.exists():
        raise FileNotFoundError(
            f"Hotel scraper not found at {scraper_path}. Keep it beside main.py."
        )

    global _HOTEL_STDOUT_WRAPPER
    original_stdout = sys.stdout
    proxy = _SafeStdoutProxy()
    try:
        # google_hotels_scraper.py wraps sys.stdout.buffer at import time.
        # Redirect that operation to a disposable in-memory buffer so its
        # TextIOWrapper can never close the server's real stdout.
        sys.stdout = proxy
        spec = importlib.util.spec_from_file_location(
            "tripwise_google_hotels_scraper", scraper_path
        )
        if spec is None or spec.loader is None:
            raise ImportError("Could not load google_hotels_scraper.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if sys.stdout is not proxy:
            _HOTEL_STDOUT_WRAPPER = sys.stdout
        return module
    finally:
        if sys.stdout is not original_stdout:
            _HOTEL_STDOUT_WRAPPER = sys.stdout
        sys.stdout = original_stdout



def _slug_city(value: str) -> str:
    """Build a conservative URL slug for route-search fallbacks."""
    import unicodedata
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-"))


def _route_search_url(mode: str, origin: str, destination: str, date: str) -> tuple[str, str]:
    """Return a route/date-specific search URL, not a fabricated individual booking URL."""
    normalized = mode.lower()
    if "bus" in normalized:
        from urllib.parse import quote
        try:
            parsed = datetime.strptime(date, "%d/%m/%Y")
            redbus_date = parsed.strftime("%d-%b-%Y")
        except (TypeError, ValueError):
            redbus_date = ""
        url = f"https://www.redbus.in/bus-tickets/{_slug_city(origin)}-to-{_slug_city(destination)}"
        if redbus_date:
            url += "?onward=" + quote(redbus_date)
        return url, "route_search"
    if "flight" in normalized:
        query = quote_plus(f"Flights from {origin} to {destination} on {date}".strip())
        return f"https://www.google.com/travel/flights?q={query}", "route_search"
    return "", ""


def _add_price_and_link_metadata(
    item: dict[str, Any], mode: str, origin: str, destination: str,
    travel_date: str, travelers: int, retrieved_at: str,
) -> dict[str, Any]:
    """Make price provenance and link specificity explicit in every transport result."""
    normalized_mode = mode.lower()
    estimated = normalized_mode in {"train", "cab"} or bool(item.get("is_estimate"))
    item["price_status"] = "estimate" if estimated else "scraped_quote"
    item["price_source"] = (
        item.get("provider") or item.get("source") or
        ("Route-based estimate" if estimated else ("Bus scraper" if normalized_mode == "bus" else "Flight scraper"))
    )
    item["price_retrieved_at"] = retrieved_at
    item["price_caveat"] = (
        "Estimated fare; not a live provider quote." if estimated else
        "Scraped display fare; recheck on the provider before booking."
    )
    if item.get("price_per_person") is not None:
        item.setdefault("price_basis", "per person; confirm group total")
    elif estimated:
        item.setdefault("price_basis", "estimated total for requested travellers")
    else:
        item.setdefault("price_basis", "displayed fare; per-person/group basis not verified")

    current = item.get("booking_link") or item.get("booking_url") or item.get("url")
    generic = not (isinstance(current, str) and current.startswith(("https://", "http://")))
    if isinstance(current, str) and current:
        lowered = current.lower().rstrip("/")
        generic = generic or lowered in {
            "https://www.redbus.in", "https://redbus.in",
            "https://www.google.com/travel/flights", "https://google.com/travel/flights",
            "https://www.google.com", "https://google.com",
        }
    if generic and normalized_mode in {"bus", "flight"}:
        url, link_type = _route_search_url(normalized_mode, origin, destination, travel_date)
        if url:
            item["booking_link"] = url
            item["booking_link_type"] = link_type
            item["booking_link_label"] = "Search route on RedBus" if normalized_mode == "bus" else "Search flights for this route"
    elif isinstance(current, str) and current.startswith(("https://", "http://")):
        item.setdefault("booking_link", current)
        item.setdefault("booking_link_type", "scraper_result")
    return item


def _get_hotel_options(location: str) -> list[dict[str, Any]]:
    module = _load_hotels_module()
    scraper = module.GoogleHotelsScraper(headless=True)
    try:
        results = scraper.scrape(location)
    except Exception as exc:
        raise RuntimeError(f"Hotel scraper failed: {exc}") from exc

    options = []
    for hotel in results[:30]:
        raw_price = hotel.get("price", "")
        options.append({
            "mode": "Accommodation",
            "provider": "Google Hotels",
            "name": hotel.get("name_en") or hotel.get("name") or "Unnamed property",
            "price_display": raw_price or None,
            "price_amount": _parse_price(raw_price),
            "currency": (
                "INR" if "₹" in str(raw_price) or "INR" in str(raw_price).upper()
                else "USD" if "$" in str(raw_price) or "USD" in str(raw_price).upper()
                else "EUR" if "€" in str(raw_price) or "EUR" in str(raw_price).upper()
                else None
            ),
            "rating": hotel.get("rating") or None,
            "details": hotel.get("info") or "",
            "price_type": "Scraped display price; stay dates not applied",
            "price_basis": "Unknown: scraper does not identify nightly vs total-stay price",
            "estimated_stay_total": None,
            "booking_link": (
            "https://www.google.com/travel/hotels"
            "?q="
            + quote_plus(
                f"{hotel.get('name_en') or hotel.get('name') or ''} {location}"
                )
            ),
            "booking_link_type": "property_search",
        })
    return options


def get_live_trip_options(
    origin: str,
    destination: str,
    travel_date: str,
    travelers: int = 1,
    transport_modes: list[str] | None = None,
    include_accommodation: bool = True,
    route_information: dict[str, float] | None = None,
    return_date: str | None = None,
) -> dict[str, Any]:
    """Return normalized transport and hotel options from existing scrapers.

    travel_date uses DD/MM/YYYY. Flights/buses can be queried without route distance.
    Estimated train/cab options require route_information with distance_km and
    optionally duration_hours.
    """
    if not origin.strip() or not destination.strip():
        raise ValueError("Origin and destination are required.")
    if not 1 <= travelers <= 20:
        raise ValueError("Travelers must be between 1 and 20.")
    try:
        datetime.strptime(travel_date, "%d/%m/%Y")
    except (TypeError, ValueError) as exc:
        raise ValueError("travel_date must use DD/MM/YYYY.") from exc
    if return_date:
        try:
            datetime.strptime(return_date, "%d/%m/%Y")
        except (TypeError, ValueError) as exc:
            raise ValueError("return_date must use DD/MM/YYYY.") from exc
        if datetime.strptime(return_date, "%d/%m/%Y") < datetime.strptime(travel_date, "%d/%m/%Y"):
            raise ValueError("return_date cannot be earlier than travel_date.")

    requested = {m.strip().lower() for m in (transport_modes or ["flight", "bus", "train", "cab"])}
    allowed = {"flight", "bus", "train", "cab"}
    invalid = requested - allowed
    if invalid:
        raise ValueError(f"Unsupported transport mode(s): {', '.join(sorted(invalid))}")

    transport: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for mode in sorted(requested):
        try:
            if mode in {"train", "cab"} and not route_information:
                errors.append({
                    "component": mode,
                    "message": "Route distance is required to calculate this estimated option.",
                })
                continue
            if mode in {"train", "cab"} and route_information:
                options = get_transport_options(
                    mode, origin, destination, travel_date, travelers, route_information
                )
            elif route_information:
                options = get_transport_options(
                    mode, origin, destination, travel_date, travelers, route_information
                )
            elif mode == "bus":
                options = get_live_buses(origin, destination, travel_date, travelers)
            else:
                # Use the existing transport module's flight wrapper/normalization.
                from transportation import _get_flight_options
                options = _get_flight_options(origin, destination, travel_date, travelers)

            for option in options:
                item = dict(option)
                item.setdefault("currency", "INR")
                item.setdefault("route", f"{origin} to {destination}")
                retrieved_at = datetime.now().astimezone().isoformat(timespec="seconds")
                item["retrieved_at"] = retrieved_at
                item = _add_price_and_link_metadata(
                    item, mode, origin, destination, travel_date, travelers, retrieved_at
                )
                transport.append(item)
        except Exception as exc:
            errors.append({"component": mode, "message": str(exc)})

    # Return transport is searched separately and only when a return date is supplied.
    return_transport: list[dict[str, Any]] = []
    if return_date:
        for mode in sorted(requested):
            try:
                if mode == "bus":
                    return_options = get_live_buses(destination, origin, return_date, travelers)
                elif mode == "flight":
                    from transportation import _get_flight_options
                    return_options = _get_flight_options(destination, origin, return_date, travelers)
                elif mode in {"train", "cab"} and route_information:
                    return_options = get_transport_options(
                        mode, destination, origin, return_date, travelers, route_information
                    )
                else:
                    continue
                for option in return_options:
                    item = dict(option)
                    item["journey_direction"] = "return"
                    item.setdefault("currency", "INR")
                    item.setdefault("route", f"{destination} to {origin}")
                    retrieved_at = datetime.now().astimezone().isoformat(timespec="seconds")
                    item["retrieved_at"] = retrieved_at
                    item = _add_price_and_link_metadata(
                        item, mode, destination, origin, return_date, travelers, retrieved_at
                    )
                    return_transport.append(item)
            except Exception as exc:
                errors.append({"component": f"return_{mode}", "message": str(exc)})

    accommodation: list[dict[str, Any]] = []
    if include_accommodation:
        try:
            accommodation = _get_hotel_options(destination)
            retrieved_at = datetime.now().astimezone().isoformat(timespec="seconds")
            for option in accommodation:
                option["retrieved_at"] = retrieved_at
                option["price_retrieved_at"] = retrieved_at
                option["price_status"] = "scraped_display_price"
                option["price_source"] = "Google Hotels scraper"
                option["price_caveat"] = (
                    "Destination-only scrape; check-in/check-out dates and guest count were not applied. "
                    "The displayed amount may be nightly or total-stay price."
                )
                option["booking_link_type"] = "property_search"
        except Exception as exc:
            errors.append({"component": "accommodation", "message": str(exc)})

    return {
        "origin": origin,
        "destination": destination,
        "travel_date": travel_date,
        "return_date": return_date,
        "travelers": travelers,
        "transport_options": transport,
        "return_transport_options": return_transport,
        "accommodation_options": accommodation,
        "errors": errors,
        "notes": [
            "Every price includes provenance and a retrieval timestamp; scraped fares are not guaranteed until confirmed at checkout.",
            "Train/cab amounts are estimates, not provider quotes.",
            "Hotel scraper searches by destination only; it does not filter by check-in/check-out dates or guest count.",
            "Hotel display prices are not multiplied into a stay total because nightly-vs-total price basis is unknown.",
            "Return transport is included only when return_date is provided; outbound and return prices are separate.",
            "Train and cab prices are estimates, not live provider quotes.",
            "Flight results are returned only when scraped IATA airport codes match the searched route; otherwise they are discarded.",
        ],
    }
