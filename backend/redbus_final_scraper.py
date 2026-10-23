from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from datetime import datetime
from urllib.parse import urlencode, quote
import time
import json
import re
import unicodedata
from urllib.parse import urlencode


def _slug_city(value):
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-"))


class RedBusHybridScraper:

    def __init__(self):
        chrome_options = Options()

        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36"
        )

        chrome_options.set_capability(
            "goog:loggingPrefs",
            {"performance": "ALL"}
        )

        self.driver = webdriver.Chrome(
            options=chrome_options
        )

    def search_buses(
        self,
        source,
        destination,
        date
    ):
        try:

            def slug_city(value):
                import re
                import unicodedata
                value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
                return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-"))

            source_slug = slug_city(source)
            destination_slug = slug_city(destination)

            # Accept both the scraper's ISO date and the API's DD/MM/YYYY date.
            try:
                date_obj = datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                date_obj = datetime.strptime(date, "%d/%m/%Y")

            formatted_date = date_obj.strftime(
                "%d-%b-%Y"
            )

            params = urlencode({
                "fromCityName": source,
                "toCityName": destination,
                "onward": formatted_date,
            })
            url = (
                f"https://www.redbus.in/bus-tickets/"
                f"{source_slug}-to-{destination_slug}?{params}"
            )

            print(
                f"\nSearching live buses: "
                f"{source} → {destination}"
            )

            self.driver.get(url)

            print("Waiting for bus data...")

            time.sleep(12)

            # Trigger additional loading
            for _ in range(3):
                self.driver.execute_script(
                    "window.scrollBy(0, 800);"
                )
                time.sleep(1)

            logs = self.driver.get_log(
                "performance"
            )

            for entry in logs:

                try:

                    log = json.loads(
                        entry["message"]
                    )["message"]

                    if (
                        log["method"]
                        != "Network.responseReceived"
                    ):
                        continue

                    response = log["params"]["response"]

                    url_received = response["url"]

                    if (
                        "searchResults"
                        not in url_received
                        or response["status"] != 200
                    ):
                        continue

                    request_id = (
                        log["params"]["requestId"]
                    )

                    response_body = (
                        self.driver.execute_cdp_cmd(
                            "Network.getResponseBody",
                            {
                                "requestId":
                                request_id
                            }
                        )
                    )

                    body = response_body.get(
                        "body",
                        ""
                    )

                    if not body:
                        continue

                    data = json.loads(body)

                    buses = (
                        self._parse_api_response(data)
                    )

                    if buses:
                        return buses

                except Exception:
                    continue

            return []

        except Exception as error:

            print(
                f"Bus API unavailable: {error}"
            )

            return []

    def _parse_api_response(self, data):

        buses = []

        checks = [

            lambda: data.get(
                "data", {}
            ).get(
                "inventories",
                []
            ),

            lambda: data.get(
                "data", {}
            ).get(
                "buses",
                []
            ),

            lambda: data.get(
                "buses",
                []
            ),

            lambda: data.get(
                "inventory",
                []
            ),

            lambda: data.get(
                "searchResult",
                {}
            ).get(
                "buses",
                []
            ),

            lambda: data.get(
                "data", {}
            ).get(
                "inventory",
                []
            ),

            lambda: data.get(
                "result",
                []
            )
        ]

        for getter in checks:

            try:

                bus_list = getter()

                if (
                    isinstance(bus_list, list)
                    and bus_list
                ):

                    for idx, bus in enumerate(
                        bus_list[:100]
                    ):

                        if not isinstance(
                            bus,
                            dict
                        ):
                            continue

                        parsed_bus = (
                            self._parse_bus_object(
                                bus,
                                idx
                            )
                        )

                        if parsed_bus:
                            buses.append(
                                parsed_bus
                            )

                    if buses:
                        return buses

            except Exception:
                continue

        return buses

    def _parse_bus_object(
        self,
        bus,
        idx
    ):

        try:

            operator = (
                bus.get("travelsName")
                or bus.get("travels")
                or bus.get("Travels")
                or bus.get("travelName")
                or bus.get("TravelName")
                or bus.get("operatorName")
                or bus.get("OperatorName")
                or bus.get("operator")
            )

            if not operator:
                return None

            bus_type = (
                bus.get("busType")
                or bus.get("BusType")
                or bus.get("vehicleType")
                or ""
            )

            departure_raw = (
                bus.get("departureTime")
                or bus.get("DepartureTime")
                or bus.get("depTime")
                or ""
            )

            arrival_raw = (
                bus.get("arrivalTime")
                or bus.get("ArrivalTime")
                or bus.get("arrTime")
                or ""
            )

            departure = (
                departure_raw.split(" ")[1][:5]
                if " " in departure_raw
                else departure_raw
            )

            arrival = (
                arrival_raw.split(" ")[1][:5]
                if " " in arrival_raw
                else arrival_raw
            )

            duration_min = bus.get(
                "journeyDurationMin",
                0
            )

            if duration_min:

                duration_hours = round(
                    duration_min / 60,
                    2
                )

                hours = duration_min // 60
                minutes = duration_min % 60

                duration_text = (
                    f"{hours}h {minutes}m"
                )

            else:

                duration_hours = None

                duration_text = (
                    bus.get("duration")
                    or bus.get("Duration")
                    or ""
                )

            # Price
            price = 0

            fare_list = bus.get(
                "fareList"
            )

            if (
                isinstance(fare_list, list)
                and fare_list
            ):
                price = min(fare_list)

            if not price:

                fares = bus.get("Fares")

                if isinstance(fares, dict):

                    price = (
                        fares.get("BasePrice")
                        or fares.get("baseFare")
                        or 0
                    )

            if not price:

                price = (
                    bus.get("fare")
                    or bus.get("Fare")
                    or bus.get("price")
                    or bus.get("totalFare")
                    or 0
                )

            seats = (
                bus.get("availableSeats")
                or bus.get("AvailableSeats")
                or bus.get("seatsAvailable")
                or ""
            )

            rating = (
                bus.get("totalRatings")
                or bus.get("rating")
                or bus.get("Rating")
                or bus.get("operatorRating")
                or ""
            )

            return {
                "operator": operator,
                "bus_type": bus_type,
                "departure": departure,
                "arrival": arrival,
                "duration": duration_text,
                "duration_hours": duration_hours,
                "price": float(price)
                if price
                else None,
                "seats_available": str(seats),
                "rating": str(rating)
            }

        except Exception as error:

            print(
                f"Error parsing bus {idx}: "
                f"{error}"
            )

            return None

    def close(self):

        try:
            self.driver.quit()
        except Exception:
            pass


def get_live_buses(
    starting_location,
    destination,
    travel_date,
    travellers=1
):
    """
    Return live redBus options normalized
    for the AI Travel Planner.
    """

    try:

        date_obj = datetime.strptime(
            travel_date,
            "%d/%m/%Y"
        )

        formatted_date = (
            date_obj.strftime("%Y-%m-%d")
        )

    except ValueError:

        raise ValueError(
            "Travel date must use DD/MM/YYYY."
        )

    scraper = None

    try:

        scraper = RedBusHybridScraper()

        buses = scraper.search_buses(
            starting_location,
            destination,
            formatted_date
        )

        normalized_buses = []

        for bus in buses:

            price = bus.get("price")

            if price is None:
                continue

            # Price returned by redBus is assumed
            # to be per passenger.
            total_price = (
                price * travellers
            )

            normalized_buses.append(
                {
                    "mode": "Bus",

                    "provider": bus.get(
                        "operator",
                        "Unknown Bus Operator"
                    ),

                    "bus_type": bus.get(
                        "bus_type",
                        ""
                    ),

                    "duration_hours":
                        bus.get(
                            "duration_hours"
                        ),

                    "duration":
                        bus.get(
                            "duration",
                            ""
                        ),

                    "price_per_person":
                        round(price),

                    "total_price":
                        round(total_price),

                    "currency": "INR",

                    "price_type": "Live",

                    "comfort_level": "Medium",

                    "booking_required": True,

                    "distance_km": None,

                    "route": (
                        f"{starting_location} "
                        f"to {destination}"
                    ),

                    "departure_time":
                        bus.get(
                            "departure"
                        ),

                    "arrival_time":
                        bus.get(
                            "arrival"
                        ),

                    "seats_available":
                        bus.get(
                            "seats_available"
                        ),

                    "rating":
                        bus.get(
                            "rating"
                        ),

                    "booking_link": (
                        "https://www.redbus.in/bus-tickets/"
                        f"{_slug_city(starting_location)}-to-{_slug_city(destination)}"
                        f"?{urlencode({'fromCityName': starting_location, 'toCityName': destination, 'onward': datetime.strptime(formatted_date, '%Y-%m-%d').strftime('%d-%b-%Y')})}"
                    )
                }
            )

        return normalized_buses

    except Exception as error:

        print(
            f"\nLive bus search failed: {error}"
        )

        return []

    finally:

        if scraper:
            scraper.close()