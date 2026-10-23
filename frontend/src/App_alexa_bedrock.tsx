
import { useState } from "react";
import {
  Plane,
  MapPin,
  CalendarDays,
  Users,
  Wallet,
  Sparkles,
  Send,
  Compass,
  ArrowRight,
  Plus,
  RefreshCw,
  CheckCircle2,
} from "lucide-react";
import "./App.css";

type Activity = {
  name: string;
  estimated_cost: number;
  day: number;
};

type Alternative = {
  name: string;
  estimated_cost: number;
  day: number;
  estimated_total: number;
  remaining_budget: number;
  over_budget_by: number;
  within_budget: boolean;
  change_in_total: number;
};

type Trip = {
  id: string;
  destination: string;
  travelers: number;
  trip_days: number;
  budget_limit: number;
  fixed_costs: Record<string, number>;
  activities: Activity[];
};

const API = "http://127.0.0.1:8000";


type LiveOption = Record<string, unknown>;

type LiveSearchResult = {
  origin: string;
  destination: string;
  travel_date: string;
  return_date?: string | null;
  travelers: number;
  transport_options: LiveOption[];
  return_transport_options: LiveOption[];
  accommodation_options: LiveOption[];
  errors: { component: string; message: string }[];
  notes: string[];
};

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  return "";
}

function formatLivePrice(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) {
    return `₹${Math.round(value).toLocaleString("en-IN")}`;
  }
  return displayValue(value);
}

function formatRetrievedAt(value: unknown): string {
  const raw = displayValue(value);
  if (!raw) return "Time unavailable";
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return raw;
  return parsed.toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

function priceStatusLabel(option: LiveOption): string {
  const status = displayValue(option.price_status).toLowerCase();
  if (status.includes("estimate")) return "Estimated fare";
  if (status.includes("scraped_display")) return "Scraped display price";
  if (status.includes("scraped")) return "Scraped fare · verify before booking";
  return "Price basis not verified";
}

function formatApiDate(value: string): string {
  if (!value) return "";
  const [year, month, day] = value.split("-"); 
  return `${day}/${month}/${year}`;
}


function getBookingUrl(
  option: LiveOption,
  origin: string,
  destination: string,
  date: string
): { url: string; label: string } | null {
  const candidates = [
    option.booking_link,
    option.booking_url,
    option.url,
  ];
  const existingLink = candidates.find(
    (value): value is string =>
      typeof value === "string" && /^https?:\/\//i.test(value)
  );
  const mode = displayValue(option.mode).toLowerCase();
  const isGenericLink = (value: string) =>
    /^https?:\/\/(www\.)?redbus\.in\/?(?:\?.*)?$/i.test(value) ||
    /^https?:\/\/(www\.)?google\.com\/travel\/(flights|hotels)\/?(?:\?.*)?$/i.test(value) ||
    /^https?:\/\/(www\.)?google\.com\/?(?:\?.*)?$/i.test(value);

  // Prefer a scraper's option-specific URL; never label a generic homepage as a booking link.
  if (!mode.includes("bus") && existingLink && !isGenericLink(existingLink)) {
    return { url: existingLink, label: "View booking source" };
  }

  const route = `${origin} to ${destination}`;
  const formattedDate = date || "";

  if (mode.includes("flight")) {
    const query = `Flights from ${route}${formattedDate ? ` on ${formattedDate}` : ""}`;
    return {
      url: `https://www.google.com/travel/flights?q=${encodeURIComponent(query)}`,
      label: "Search these flights",
    };
  }

  if (mode.includes("bus")) {
    // Open RedBus directly on its route page instead of sending users to Google.
    // RedBus may still ask the user to confirm the cities/date before showing fares.
    const slug = (value: string) =>
      value
        .normalize("NFKD")
        .replace(/[\u0300-\u036f]/g, "")
        .toLowerCase()
        .trim()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "");

    const redBusRoute = `${slug(origin)}-to-${slug(destination)}`;
    const formatRedBusDate = (date: string) => {
      // Supports YYYY-MM-DD and DD/MM/YYYY
      const parts = date.includes("/")
        ? date.split("/")
        : date.split("-");

      let day: string;
      let month: string;
      let year: string;

      if (date.includes("/")) {
        [day, month, year] = parts;
      } else {
        [year, month, day] = parts;
      }

      const monthNames = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
      ];

      return `${day}-${monthNames[Number(month) - 1]}-${year}`;
    };
    const redBusDate = date ? formatRedBusDate(date) : "";
    const params = new URLSearchParams();

    // RedBus can reset the date to today when its canonical city identifiers
    // and both date parameters are missing. Include the identifiers confirmed
    // by the working Delhi -> Manali URL, plus city names for the route page.
    const knownRedBusCityIds: Record<string, string> = {
      delhi: "733",
      manali: "757",
    };
    const originKey = origin.trim().toLowerCase();
    const destinationKey = destination.trim().toLowerCase();
    const originCityId = knownRedBusCityIds[originKey];
    const destinationCityId = knownRedBusCityIds[destinationKey];

    if (originCityId) params.set("fromCityId", originCityId);
    params.set("fromCityName", origin);
    if (destinationCityId) params.set("toCityId", destinationCityId);
    params.set("toCityName", destination);
    if (redBusDate) {
      params.set("onward", redBusDate);
      params.set("doj", redBusDate);
    }
    params.set("ref", "search");

    return {
      url: `https://www.redbus.in/bus-tickets/${redBusRoute}?${params.toString()}`,
      label: "Search buses on RedBus",
    };
  }

  return null;
}

function App() {
  const [, setTripId] = useState("");
  const [trip, setTrip] = useState<Trip | null>(null);
  const [message, setMessage] = useState("");
  const [assistantReply, setAssistantReply] = useState("");
  const [tripPrompt, setTripPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [pendingAlternative, setPendingAlternative] = useState<Alternative | null>(null);
  const [destination, setDestination] = useState("Manali");
  const [travelers, setTravelers] = useState(3);
  const [days, setDays] = useState(4);
  const [budget, setBudget] = useState(30000);

  const fixedTotal = trip
    ? Object.values(trip.fixed_costs).reduce<number>((a, b) => a + Number(b), 0)
    : 0;

  const activityTotal = trip
    ? trip.activities.reduce((sum, activity) => sum + activity.estimated_cost, 0)
    : 0;

  const total = fixedTotal + activityTotal;
  const remaining = trip ? trip.budget_limit - total : 0;

  async function loadTrip(id: string) {
    const response = await fetch(`${API}/trips/${id}`);
    if (!response.ok) throw new Error("Could not retrieve this trip.");
    const data: Trip = await response.json();
    setPendingAlternative(null);
    setTrip(data);
    setTripId(data.id);
    setDestination(data.destination);
    setTravelers(data.travelers);
    setDays(data.trip_days);
    setBudget(data.budget_limit);
  }

  
  const [origin, setOrigin] = useState("Delhi");
  const [travelDate, setTravelDate] = useState("2026-10-25");
  const [returnDate, setReturnDate] = useState("");
  const [transportModes, setTransportModes] = useState<string[]>([
    "bus",
    "flight",
  ]);
  const [includeAccommodation, setIncludeAccommodation] = useState(false);
  const [liveLoading, setLiveLoading] = useState(false);
  const [liveError, setLiveError] = useState("");
  const [liveResult, setLiveResult] = useState<LiveSearchResult | null>(null);
  const [selectedOutbound, setSelectedOutbound] = useState<number | null>(null);
  const [selectedReturn, setSelectedReturn] = useState<number | null>(null);
  const [selectedHotel, setSelectedHotel] = useState<number | null>(null);
  const [sortPrice, setSortPrice] = useState("low");
  const [minRating, setMinRating] = useState("0");
  const [interests, setInterests] = useState<string[]>(["nature", "food", "culture"]);
  const [budgetAssessment, setBudgetAssessment] = useState<{estimated:number; shortfall:number; details:string[]} | null>(null);

  function toggleTransportMode(mode: string) {
    setTransportModes((current) =>
      current.includes(mode)
        ? current.filter((item) => item !== mode)
        : [...current, mode]
    );
  }

  async function searchLiveOptions() {
    if (!origin.trim() || !destination.trim()) {
      setLiveError("Enter both your origin and destination.");
      return;
    }

    if (!travelDate || (returnDate && returnDate < travelDate)) {
      setLiveError("Choose a valid departure date and return date.");
      return;
    }

    if (transportModes.length === 0) {
      setLiveError("Select at least one transport mode.");
      return;
    }

    setLiveLoading(true);
    setLiveError("");
    setLiveResult(null);
    setSelectedOutbound(null);
    setSelectedReturn(null);
    setSelectedHotel(null);
    setBudgetAssessment(null);

    try {
      const response = await fetch(`${API}/trips/live-options`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          origin: origin.trim(),
          destination: destination.trim(),
          travel_date: formatApiDate(travelDate),
          return_date: returnDate ? formatApiDate(returnDate) : null,
          travelers,
          transport_modes: transportModes,
          include_accommodation: includeAccommodation,
        }),
      });

      const data = await response.json().catch(() => null);

      if (!response.ok) {
        throw new Error(
          typeof data?.detail === "string"
            ? data.detail
            : "Live search failed. Check that the backend is running."
        );
      }

      setLiveResult(data as LiveSearchResult);
    } catch (error) {
      setLiveError(
        error instanceof Error
          ? error.message
          : "Unable to connect to the TripWise backend."
      );
    } finally {
      setLiveLoading(false);
    }
  }

  const numericPrice = (option: LiveOption | undefined): number | null => {
    if (!option) return null;
    for (const key of ["total_price", "price_per_person", "price_amount", "displayed_price"]) {
      const value = option[key];
      if (typeof value === "number" && Number.isFinite(value) && value >= 0) {
        return key === "price_per_person" ? value * travelers : value;
      }
      if (typeof value === "string") {
        const parsed = Number(value.replace(/[^0-9.]/g, ""));
        if (Number.isFinite(parsed) && parsed > 0) return key === "price_per_person" ? parsed * travelers : parsed;
      }
    }
    return null;
  };

  const optionRating = (option: LiveOption): number | null => {
    const value = option.rating ?? option.review_rating ?? option.stars;
    const rating = typeof value === "number" ? value : Number(value);
    return Number.isFinite(rating) && rating > 0 ? rating : null;
  };

  const sortedOptions = (options: LiveOption[]) => options
    .map((option, index) => ({ option, index }))
    .filter(({ option }) => {
      if (Number(minRating) <= 0) return true;
      const rating = optionRating(option);
      return rating !== null && rating >= Number(minRating);
    })
    .sort((a, b) => {
      const pa = numericPrice(a.option), pb = numericPrice(b.option);
      if (pa === null && pb === null) return 0;
      if (pa === null) return 1;
      if (pb === null) return -1;
      return sortPrice === "high" ? pb - pa : pa - pb;
    });

  const activitySuggestions = [
    { name: "Guided nature walk", category: "nature", cost: 0, day: 1 },
    { name: "Local food street or market", category: "food", cost: 350 * travelers, day: 1 },
    { name: "Museum or heritage site", category: "culture", cost: 200 * travelers, day: 2 },
    { name: "Scenic viewpoint / sunrise", category: "nature", cost: 150 * travelers, day: 2 },
    { name: "Guided adventure activity", category: "adventure", cost: 1200 * travelers, day: 3 },
    { name: "Local cooking or craft experience", category: "culture", cost: 700 * travelers, day: 3 },
    { name: "Cafe and regional speciality tasting", category: "food", cost: 500 * travelers, day: 2 },
    { name: "Lake, river or garden visit", category: "nature", cost: 100 * travelers, day: 3 },
  ];

  async function createTrip() {
    if (!liveResult) {
      setNotice("Search live options first, then select your outbound transport before generating the itinerary.");
      return;
    }
    if (selectedOutbound === null) {
      setNotice("Select an outbound transport option before generating your itinerary.");
      return;
    }
    const outbound = selectedOutbound !== null ? liveResult?.transport_options[selectedOutbound] : undefined;
    const inbound = selectedReturn !== null ? liveResult?.return_transport_options[selectedReturn] : undefined;
    const hotel = selectedHotel !== null ? liveResult?.accommodation_options[selectedHotel] : undefined;
    const outboundCost = numericPrice(outbound);
    const returnCost = numericPrice(inbound);
    const transportCost = (outboundCost ?? 0) + (returnCost ?? 0);
    const hotelRawCost = numericPrice(hotel);
    const hotelBasis = displayValue(hotel?.price_basis).toLowerCase();
    const hotelCostIsTotal = hotelRawCost !== null && /(total|whole stay|stay total)/i.test(hotelBasis);
    const accommodationCost = hotelCostIsTotal ? hotelRawCost! : 0;
    const foodCost = Math.round(600 * travelers * Math.max(1, days));
    const localTransportCost = Math.round(250 * travelers * Math.max(1, days));
    const chosenActivities = activitySuggestions.filter(item => interests.includes(item.category))
      .sort((a, b) => a.cost - b.cost).slice(0, Math.min(days, 4));
    const activityCost = chosenActivities.reduce((sum, item) => sum + item.cost, 0);
    const contingency = Math.round((transportCost + accommodationCost + foodCost + localTransportCost + activityCost) * 0.1);
    const estimated = transportCost + accommodationCost + foodCost + localTransportCost + activityCost + contingency;
    const details = [
      `Transport: ${currency(transportCost)}${outboundCost === null ? " (price unavailable; excluded)" : ""}`,
      `Accommodation: ${hotel ? (hotelCostIsTotal ? currency(accommodationCost) : "selected, but total stay price is unverified and excluded") : "not selected"}`,
      ...(hotel && !hotelCostIsTotal ? ["Budget warning: the selected stay price is not a verified whole-stay total; actual accommodation may increase the final cost."] : []),
      `Food estimate: ${currency(foodCost)}`,
      `Local transport estimate: ${currency(localTransportCost)}`,
      `Activities estimate: ${currency(activityCost)}`,
      `10% contingency: ${currency(contingency)}`,
    ];
    setBudgetAssessment({ estimated, shortfall: Math.max(0, estimated - budget), details });
    if (estimated > budget) {
      setNotice(`Your budget looks too low for these selections. Estimated minimum: ${currency(estimated)}; budget: ${currency(budget)}; shortfall: ${currency(estimated - budget)}. Try cheaper transport, fewer paid activities, or a higher budget.`);
      return;
    }

    setLoading(true);
    setNotice("");
    try {
      const activities = chosenActivities.length
        ? chosenActivities.map((item, index) => ({ name: item.name, estimated_cost: item.cost, day: Math.min(days, item.day || index + 1) }))
        : [{ name: "Explore a free local area", estimated_cost: 0, day: 1 }];
      const response = await fetch(`${API}/trips`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          destination, travelers, trip_days: days, budget_limit: budget,
          fixed_costs: { transport: transportCost, accommodation: accommodationCost, food: foodCost, local_transport: localTransportCost, contingency },
          activities,
        }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) throw new Error(data?.detail ?? "Trip creation failed.");
      await loadTrip(data.trip.id);
      setNotice(hotel && !hotelCostIsTotal
        ? "Itinerary created using your selected transport and estimates. IMPORTANT: the selected accommodation price basis is unverified and excluded from the total, so the actual trip may exceed your budget. No booking was made."
        : "Itinerary created using your selected transport and cost estimates. No booking was made.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  async function planTripFromPrompt() {
    const prompt = tripPrompt.trim();
    if (!prompt) return;

    setLoading(true);
    setNotice("");
    setLiveError("");
    try {
      const parseResponse = await fetch(`${API}/trips/parse-intent`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: prompt }),
      });
      const intent = await parseResponse.json().catch(() => null);
      if (!parseResponse.ok) {
        throw new Error(intent?.detail ?? "Could not understand the trip request.");
      }
      if (!intent || intent.error) throw new Error(intent?.error ?? "Could not parse that trip request.");

      const missing: string[] = [];
      if (!intent.destination) missing.push("destination");
      if (!intent.trip_days) missing.push("trip duration (for example, 4 days)");
      if (!intent.travelers) missing.push("traveller count (for example, 3 travellers)");
      if (!intent.budget) missing.push("budget (for example, ₹30000)");
      if (missing.length) {
        setNotice(`I still need ${missing.join(", ")}. Add these details to your request, then try again.`);
        return;
      }

      const parsedDestination = String(intent.destination).trim();
      const parsedOrigin = String(intent.origin || origin).trim();
      const parsedTravelers = Number(intent.travelers);
      const parsedDays = Number(intent.trip_days);
      const parsedBudget = Number(intent.budget);
      const parsedStartDate = typeof intent.start_date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(intent.start_date)
        ? intent.start_date
        : travelDate;
      const parsedReturnDate = typeof intent.end_date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(intent.end_date)
        ? intent.end_date
        : "";

      if (!Number.isFinite(parsedTravelers) || !Number.isFinite(parsedDays) || !Number.isFinite(parsedBudget) || parsedTravelers < 1 || parsedDays < 1 || parsedDays > 30 || parsedBudget <= 0) {
        throw new Error("The request returned invalid trip details. Check traveller count, duration, and budget.");
      }
      if (parsedReturnDate && parsedReturnDate < parsedStartDate) {
        throw new Error("The return date cannot be earlier than the departure date.");
      }

      const parsedModes = Array.isArray(intent.transport_preferences)
        ? intent.transport_preferences.filter((mode: string) => ["flight", "bus", "train", "cab"].includes(mode))
        : [];
      const modesToSearch = parsedModes.length ? parsedModes : transportModes;
      const wantsStay = Boolean(intent.needs_live_stay_prices) || (Array.isArray(intent.stay_preferences) && intent.stay_preferences.length > 0);

      // Update the visible form to match the request, then fetch live options using
      // the parsed local values (rather than waiting for React state to update).
      setDestination(parsedDestination);
      setOrigin(parsedOrigin);
      setTravelers(parsedTravelers);
      setDays(parsedDays);
      setBudget(parsedBudget);
      setTravelDate(parsedStartDate);
      setReturnDate(parsedReturnDate);
      setTransportModes(modesToSearch);
      setIncludeAccommodation(wantsStay);
      setSelectedOutbound(null);
      setSelectedReturn(null);
      setSelectedHotel(null);
      setLiveResult(null);
      setBudgetAssessment(null);
      setLiveLoading(true);

      const searchResponse = await fetch(`${API}/trips/live-options`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          origin: parsedOrigin,
          destination: parsedDestination,
          travel_date: formatApiDate(parsedStartDate),
          return_date: parsedReturnDate ? formatApiDate(parsedReturnDate) : null,
          travelers: parsedTravelers,
          transport_modes: modesToSearch,
          include_accommodation: wantsStay,
        }),
      });
      const searchData = await searchResponse.json().catch(() => null);
      if (!searchResponse.ok) {
        throw new Error(searchData?.detail ?? "Trip details were understood, but the live search failed.");
      }
      setLiveResult(searchData as LiveSearchResult);
      setTripPrompt("");
      setNotice("Trip details filled in and options searched. Select your outbound transport and, if shown, return transport or accommodation. Then generate the itinerary. Prices are scraped or estimated and are not bookings.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Something went wrong.");
    } finally {
      setLoading(false);
      setLiveLoading(false);
    }
  }

  async function sendMessage() {
    const text = message.trim();
    if (!text || !trip) return;

    setLoading(true);
    setNotice("");
    setAssistantReply("");
    setPendingAlternative(null);

    try {
      const response = await fetch("http://127.0.0.1:8002/assistant/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          trip_id: trip.id,
          trip_context: {
            destination: trip.destination,
            travelers: trip.travelers,
            trip_days: trip.trip_days,
            budget_limit: trip.budget_limit,
            fixed_costs: trip.fixed_costs,
            activities: trip.activities,
          },
        }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(data?.detail ?? "TripWise assistant could not process this request.");
      }

      setAssistantReply(String(data?.reply ?? "I couldn't generate a response. Please try again."));
      const proposed = data?.suggested_alternative;
      if (proposed && typeof proposed.name === "string") {
        setPendingAlternative({
          name: proposed.name,
          estimated_cost: Number(proposed.estimated_cost ?? 0),
          day: Number(proposed.day ?? trip.activities[0]?.day ?? 1),
          estimated_total: Number(proposed.estimated_total ?? 0),
          remaining_budget: Number(proposed.remaining_budget ?? 0),
          over_budget_by: Number(proposed.over_budget_by ?? 0),
          within_budget: Boolean(proposed.within_budget),
          change_in_total: Number(proposed.change_in_total ?? 0),
        });
        setNotice("Alternative prepared by the TripWise MCP tools. Review it before applying.");
      }
      setMessage("");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  async function applyAlternative() {
    if (!trip || !pendingAlternative) return;

    setLoading(true);
    setNotice("");

    try {
      const response = await fetch(`${API}/trips/${trip.id}/replan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_index: 0,
          new_activity_name: pendingAlternative.name,
          new_activity_cost: pendingAlternative.estimated_cost,
          new_activity_day: pendingAlternative.day,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => null);
        throw new Error(errorData?.detail ?? "Could not update the itinerary.");
      }

      await loadTrip(trip.id);
      setMessage("");
      setPendingAlternative(null);
      setNotice("Itinerary updated successfully.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  const currency = (amount: number) =>
    `₹${Math.round(amount).toLocaleString("en-IN")}`;

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#">
          <span className="brand-icon"><Compass size={23} /></span>
          <span>tripwise<span className="brand-dot">.</span></span>
        </a>

        <p className="side-label">WORKSPACE</p>
        <button className="nav-item active"><Compass size={18} /> My trips</button>
        <button className="nav-item" onClick={() => setTrip(null)}><Plus size={18} /> New trip</button>

        <div className="sidebar-bottom">
          <div className="assistant-mini">
            <Sparkles size={20} />
            <div>
              <strong>TripWise AI</strong>
              <span>Your travel copilot</span>
            </div>
          </div>
          <span className="version-label">HACKATHON EDITION · 2026</span>
        </div>
      </aside>

      <section className="main-area">
        <header className="topbar">
          <div className="breadcrumb">Workspace <span>/</span> My trips</div>
          <div className="profile"><span className="status-dot" /> Prototype</div>
        </header>

        <div className="page-content">
          <div className="page-heading">
            <div>
              <p className="eyebrow">YOUR NEXT ADVENTURE STARTS HERE</p>
              <h1>{trip ? `Your ${trip.destination} escape` : "Plan something unforgettable."}</h1>
              <p className="subtitle">Thoughtful itineraries. Smarter budgets. Better journeys.</p>
            </div>
            <div className="heading-icon"><Plane size={27} /></div>
          </div>
          
          <section className="live-search-panel">
            <div className="live-search-heading">
              <div>
                <p className="eyebrow">COMPARE YOUR OPTIONS</p>
                <h2>Live travel search</h2>
                <p className="subtitle">
                  Search transport options for your next journey.
                </p>
              </div>
              <div className="heading-icon">
                <Plane size={24} />
              </div>
            </div>

            <div className="live-form-grid">
              <label>
                From
                <div className="input-wrap">
                  <MapPin size={17} />
                  <input
                    value={origin}
                    onChange={(e) => setOrigin(e.target.value)}
                    placeholder="e.g. Delhi"
                  />
                </div>
              </label>

              <label>
                To
                <div className="input-wrap">
                  <MapPin size={17} />
                  <input
                    value={destination}
                    onChange={(e) => setDestination(e.target.value)}
                    placeholder="e.g. Manali"
                  />
                </div>
              </label>

              <label>
                Departure
                <div className="input-wrap">
                  <CalendarDays size={17} />
                  <input
                    type="date"
                    value={travelDate}
                    onChange={(e) => setTravelDate(e.target.value)}
                    required
                  />
                </div>
              </label>

              <label>
                Return (optional)
                <div className="input-wrap">
                  <CalendarDays size={17} />
                  <input
                    type="date"
                    min={travelDate}
                    value={returnDate}
                    onChange={(e) => setReturnDate(e.target.value)}
                  />
                </div>
              </label>

              <label>
                Travellers
                <div className="input-wrap">
                  <Users size={17} />
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={travelers}
                    onChange={(e) => setTravelers(Number(e.target.value))}
                  />
                </div>
              </label>
            </div>

            <div className="transport-picker">
              <span className="field-title">Transport modes</span>
              <div className="transport-chips">
                {["bus", "flight", "train", "cab"].map((mode) => (
                  <label className="transport-chip" key={mode}>
                    <input
                      type="checkbox"
                      checked={transportModes.includes(mode)}
                      onChange={() => toggleTransportMode(mode)}
                    />
                    <span>
                      {mode.charAt(0).toUpperCase() + mode.slice(1)}
                    </span>
                  </label>
                ))}
              </div>
            </div>

            <label className="stay-toggle">
              <input
                type="checkbox"
                checked={includeAccommodation}
                onChange={(e) => setIncludeAccommodation(e.target.checked)}
              />
              Include accommodation search
            </label>

            <button
              className="primary-button live-search-button"
              onClick={() => void searchLiveOptions()}
              disabled={liveLoading}
            >
              {liveLoading ? (
                <>
                  <RefreshCw size={17} /> Searching options...
                </>
              ) : (
                <>
                  <Compass size={17} /> Search transport options
                  <ArrowRight size={17} />
                </>
              )}
            </button>

            {liveError && (
              <div className="global-notice" role="alert">
                {liveError}
              </div>
            )}

            {liveResult && (
              <div className="live-results">
                <div className="section-heading">
                  <div>
                    <h2>
                      {liveResult.origin} → {liveResult.destination}
                    </h2>
                    <p>
                      {liveResult.travel_date} · {liveResult.travelers} traveller(s)
                    </p>
                  </div>
                  <span className="results-count">
                    {liveResult.transport_options?.length ?? 0} outbound
                  </span>
                </div>

                {liveResult.errors?.length > 0 && (
                  <div className="global-notice">
                    {liveResult.errors.map((item, index) => (
                      <p key={`${item.component}-${index}`}>
                        <strong>{item.component}:</strong> {item.message}
                      </p>
                    ))}
                  </div>
                )}

                <div className="live-form-grid">
                  <label>Sort by price
                    <select value={sortPrice} onChange={(e) => setSortPrice(e.target.value)}>
                      <option value="low">Lowest first</option>
                      <option value="high">Highest first</option>
                    </select>
                  </label>
                  <label>Minimum rating
                    <select value={minRating} onChange={(e) => setMinRating(e.target.value)}>
                      <option value="0">Any / unavailable</option>
                      <option value="4">4.0 and above</option>
                      <option value="4.5">4.5 and above</option>
                    </select>
                  </label>
                </div>
                {liveResult.transport_options?.length ? (
                  sortedOptions(liveResult.transport_options).map(({option, index}) => {
                    const price =
                      option.price_per_person ?? option.price_display ??
                      option.price_amount ?? option.displayed_price;
                    const totalPrice = option.total_price;
                    const booking = getBookingUrl(
                      option,
                      liveResult.origin,
                      liveResult.destination,
                      travelDate
                    );

                    return (
                      <article className="live-option-card" key={index}>
                        <div className="live-option-top">
                          <div>
                            <span className="option-mode">
                              {displayValue(option.mode) || "Transport"}
                            </span>
                            <h3>
                              {displayValue(option.provider) ||
                                displayValue(option.name) ||
                                "Travel option"}
                            </h3>
                          </div>
                          <div className="live-price">
                            <strong>
                              {price !== undefined && price !== null
                                ? formatLivePrice(price)
                                : "Price unavailable"}
                            </strong>
                            <span>
                              {option.price_per_person !== undefined &&
                              option.price_per_person !== null
                                ? "per person"
                                : "displayed fare"}
                            </span>
                          </div>
                        </div>

                        <p className="option-route">
                          {displayValue(option.route) ||
                            `${liveResult.origin} → ${liveResult.destination}`}
                        </p>

                        <div className="option-details">
                          {(displayValue(option.departure_time) ||
                            displayValue(option.departure)) && (
                            <span>
                              <strong>Departure</strong>
                              {displayValue(option.departure_time) ||
                                displayValue(option.departure)}
                            </span>
                          )}
                          {(displayValue(option.arrival_time) ||
                            displayValue(option.arrival)) && (
                            <span>
                              <strong>Arrival</strong>
                              {displayValue(option.arrival_time) ||
                                displayValue(option.arrival)}
                            </span>
                          )}
                          {displayValue(option.duration) && (
                            <span>
                              <strong>Duration</strong>
                              {displayValue(option.duration)}
                            </span>
                          )}
                        </div>

                        {totalPrice !== undefined && totalPrice !== null ? (
                          <p className="price-note">
                            Group total: {formatLivePrice(totalPrice)}
                          </p>
                        ) : (
                          <p className="price-note">
                            Total fare not verified. Confirm the fare basis
                            before comparing the full trip cost.
                          </p>
                        )}

                        {displayValue(option.fare_type) && (
                          <p className="price-note">
                            Fare type: {displayValue(option.fare_type)}
                          </p>
                        )}
                        <p className="price-note">
                          <strong>{priceStatusLabel(option)}</strong>
                          {displayValue(option.price_source) ? ` · Source: ${displayValue(option.price_source)}` : ""}
                          {displayValue(option.price_basis) ? ` · ${displayValue(option.price_basis)}` : ""}
                        </p>
                        {displayValue(option.price_caveat) && (
                          <p className="price-note">{displayValue(option.price_caveat)}</p>
                        )}
                        <p className="price-note">
                          Retrieved: {formatRetrievedAt(option.price_retrieved_at || option.retrieved_at)}
                        </p>

                        <button
                          className="primary-button"
                          type="button"
                          onClick={() => setSelectedOutbound(index)}
                        >
                          {selectedOutbound === index ? <><CheckCircle2 size={16} /> Selected for itinerary</> : "Use this transport"}
                        </button>
                        {booking && (
                          <a
                            className="booking-link"
                            href={booking.url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {booking.label} <ArrowRight size={14} />
                          </a>
                        )}
                      </article>
                    );
                  })
                ) : (
                  <p className="empty-results">
                    No outbound options were returned for this search.
                    Check the component errors above or try another date.
                  </p>
                )}

                {liveResult.return_transport_options?.length > 0 && (
                  <div className="return-results">
                    <h2>Return journey</h2>
                    {sortedOptions(liveResult.return_transport_options).map(({option, index}) => {
                      const booking = getBookingUrl(
                        option,
                        liveResult.destination,
                        liveResult.origin,
                        returnDate || liveResult.return_date || ""
                      );

                      return (
                        <article className="live-option-card" key={index}>
                          <h3>
                            {displayValue(option.provider) ||
                              displayValue(option.name) ||
                              "Return option"}
                          </h3>
                          <p className="option-route">
                            {displayValue(option.route) ||
                              `${liveResult.destination} → ${liveResult.origin}`}
                          </p>
                          <strong>
                            {formatLivePrice(
                              option.price_per_person ??
                              option.price_display ??
                              option.price_amount ??
                              option.displayed_price
                            ) || "Price unavailable"}
                          </strong>
                          <p className="price-note">
                            Return fare is shown separately; do not assume it is
                            included in the outbound fare.
                          </p>
                          <p className="price-note">
                            <strong>{priceStatusLabel(option)}</strong>
                            {displayValue(option.price_source) ? ` · Source: ${displayValue(option.price_source)}` : ""}
                            {displayValue(option.price_basis) ? ` · ${displayValue(option.price_basis)}` : ""}
                          </p>
                          {displayValue(option.price_caveat) && (
                            <p className="price-note">{displayValue(option.price_caveat)}</p>
                          )}
                          <p className="price-note">
                            Retrieved: {formatRetrievedAt(option.price_retrieved_at || option.retrieved_at)}
                          </p>
                          <button className="primary-button" type="button" onClick={() => setSelectedReturn(index)}>
                            {selectedReturn === index ? <><CheckCircle2 size={16} /> Return selected</> : "Use this return"}
                          </button>
                          {booking && (
                            <a
                              className="booking-link"
                              href={booking.url}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              {booking.label} <ArrowRight size={14} />
                            </a>
                          )}
                        </article>
                      );
                    })}
                  </div>
                )}

                {includeAccommodation && (
                  <div className="return-results">
                    <h2>Accommodation</h2>
                    {liveResult.accommodation_options?.length ? (
                      sortedOptions(liveResult.accommodation_options).map(({option: hotel, index}) => {
                        const hotelName = displayValue(hotel.name);
                        const suppliedHotelLink =
                          displayValue(hotel.booking_link) ||
                          displayValue(hotel.booking_url) ||
                          displayValue(hotel.url);
                        const isGenericHotelLink =
                          /^https?:\/\/(www\.)?google\.com\/travel\/hotels\/?(?:\?.*)?$/i.test(suppliedHotelLink);
                        const accommodationUrl =
                          /^https?:\/\//i.test(suppliedHotelLink) && !isGenericHotelLink
                            ? suppliedHotelLink
                            : `https://www.google.com/travel/hotels?q=${encodeURIComponent(
                                `${hotelName || "hotels"} ${liveResult.destination}`
                              )}`;

                        return (
                          <article className="live-option-card" key={index}>
                            <h3>{hotelName || "Accommodation option"}</h3>
                            <p>{displayValue(hotel.details)}</p>
                            <strong>
                              {displayValue(hotel.price_display) ||
                                formatLivePrice(hotel.price_amount) ||
                                "Price unavailable"}
                            </strong>
                            <p className="price-note">
                              {displayValue(hotel.price_basis) ||
                                "Stay total not verified. Check dates and price basis."}
                            </p>
                            <p className="price-note">
                              <strong>{priceStatusLabel(hotel)}</strong>
                              {displayValue(hotel.price_source) ? ` · Source: ${displayValue(hotel.price_source)}` : ""}
                            </p>
                            {displayValue(hotel.price_caveat) && (
                              <p className="price-note">{displayValue(hotel.price_caveat)}</p>
                            )}
                            <p className="price-note">
                              Retrieved: {formatRetrievedAt(hotel.price_retrieved_at || hotel.retrieved_at)}
                            </p>
                            <button className="primary-button" type="button" onClick={() => setSelectedHotel(index)}>
                              {selectedHotel === index ? <><CheckCircle2 size={16} /> Stay selected</> : "Use this stay"}
                            </button>
                            <a
                              className="booking-link"
                              href={accommodationUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              Find this property <ArrowRight size={14} />
                            </a>
                          </article>
                        );
                      })
                    ) : (
                      <p className="empty-results">
                        No accommodation options were returned.
                      </p>
                    )}
                  </div>
                )}

                {liveResult.notes?.length > 0 && (
                  <div className="search-notes">
                    <strong>Before you book</strong>
                    <ul>
                      {liveResult.notes.map((note, index) => (
                        <li key={index}>{note}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </section>


          {!trip && (
            <section className="create-panel">
              <div className="panel-heading">
                <div><h2>What do you want to experience?</h2><p>Choose interests to shape your itinerary.</p></div>
                <Sparkles size={22} />
              </div>
              <div className="transport-chips">
                {["adventure", "food", "nature", "culture"].map(category => (
                  <label className="transport-chip" key={category}>
                    <input type="checkbox" checked={interests.includes(category)} onChange={() => setInterests(current => current.includes(category) ? current.filter(item => item !== category) : [...current, category])} />
                    <span>{category.charAt(0).toUpperCase() + category.slice(1)}</span>
                  </label>
                ))}
              </div>
              <p className="price-note">Activity prices are estimates, not live quotes. The planner will use your selected transport and only count accommodation when its total-stay price basis is clear.</p>
              {budgetAssessment && (
                <div className="search-notes">
                  <strong>Budget estimate: {currency(budgetAssessment.estimated)}</strong>
                  {budgetAssessment.details.map((detail, i) => <p key={i}>{detail}</p>)}
                  {budgetAssessment.shortfall > 0 && <p role="alert">Short by {currency(budgetAssessment.shortfall)}. Adjust selections or budget.</p>}
                </div>
              )}
              <button className="primary-button" type="button" onClick={() => void createTrip()} disabled={loading}>
                {loading ? "Building itinerary..." : "Generate itinerary from my selections"} <ArrowRight size={18} />
              </button>
            </section>
          )}

          {!trip ? (
            <section className="create-panel">
              <div className="panel-heading">
                <div>
                  <h2>Build your next trip</h2>
                  <p>Tell us the basics. We'll take it from there.</p>
                </div>
                <Sparkles size={22} />
              </div>

              <form className="natural-language-form" onSubmit={(event) => { event.preventDefault(); void planTripFromPrompt(); }}>
                <label>
                  Describe your trip in one message
                  <div className="input-wrap"><Sparkles size={18} /><input value={tripPrompt} onChange={(e) => setTripPrompt(e.target.value)} placeholder="e.g. Delhi to Manali, 3 travellers, 4 days, ₹30,000" required /></div>
                </label>
                <button className="primary-button" type="submit" disabled={loading || !tripPrompt.trim()}>
                  {loading ? "Understanding your request..." : "Plan with TripWise AI"} <ArrowRight size={18} />
                </button>
              </form>
              <div className="form-divider"><span>or enter details manually</span></div>
              <form onSubmit={(event) => { event.preventDefault(); void createTrip(); }}>
                <label>
                  Destination
                  <div className="input-wrap"><MapPin size={18} /><input value={destination} onChange={(e) => setDestination(e.target.value)} required /></div>
                </label>
                <div className="form-row">
                  <label>
                    Travellers
                    <div className="input-wrap"><Users size={18} /><input type="number" min="1" max="20" value={travelers} onChange={(e) => setTravelers(Number(e.target.value))} required /></div>
                  </label>
                  <label>
                    Duration (days)
                    <div className="input-wrap"><CalendarDays size={18} /><input type="number" min="1" max="30" value={days} onChange={(e) => setDays(Number(e.target.value))} required /></div>
                  </label>
                </div>
                <label>
                  Total trip budget (INR)
                  <div className="input-wrap"><Wallet size={18} /><input type="number" min="1" value={budget} onChange={(e) => setBudget(Number(e.target.value))} required /></div>
                </label>
                <button className="primary-button" type="submit" disabled={loading}>
                  {loading ? "Building itinerary..." : "Generate itinerary"} <ArrowRight size={18} />
                </button>
              </form>
            </section>
          ) : (
            <>
              <section className="stats-grid">
                <div className="stat-card"><span className="stat-icon"><Wallet size={19} /></span><span className="stat-label">TOTAL BUDGET</span><strong>{currency(trip.budget_limit)}</strong><small>Trip spending limit</small></div>
                <div className="stat-card"><span className="stat-icon"><CalendarDays size={19} /></span><span className="stat-label">DURATION</span><strong>{trip.trip_days} days</strong><small>{trip.travelers} travellers</small></div>
                <div className="stat-card"><span className="stat-icon"><Compass size={19} /></span><span className="stat-label">ESTIMATED COST</span><strong>{currency(total)}</strong><small>Across all categories</small></div>
                <div className="stat-card"><span className="stat-icon"><Sparkles size={19} /></span><span className="stat-label">REMAINING</span><strong className={remaining < 0 ? "over-budget" : ""}>{currency(remaining)}</strong><small>{remaining < 0 ? "Over budget" : "Available to spend"}</small></div>
              </section>

              <div className="content-grid">
                <section className="itinerary-panel">
                  <div className="section-heading">
                    <div><h2>Your itinerary</h2><p>A snapshot of your planned experiences</p></div>
                    <button className="icon-button" onClick={() => void loadTrip(trip.id)} title="Refresh trip"><RefreshCw size={17} /></button>
                  </div>

                  {trip.activities.map((activity, index) => (
                    <article className="activity-card" key={`${activity.name}-${index}`}>
                      <div className="day-marker">0{activity.day}</div>
                      <div className="activity-info"><span>DAY {activity.day}</span><h3>{activity.name}</h3><p>Estimated activity cost</p></div>
                      <strong className="activity-cost">{currency(activity.estimated_cost)}</strong>
                    </article>
                  ))}

                  <div className="budget-section">
                    <h3>Budget overview</h3>
                    {Object.entries(trip.fixed_costs).map(([category, amount]) => (
                      <div className="budget-line" key={category}>
                        <div><span>{category}</span><strong>{currency(Number(amount))}</strong></div>
                        <div className="progress-track"><div className="progress-fill" style={{ width: `${Math.min(100, Number(amount) / trip.budget_limit * 100)}%` }} /></div>
                      </div>
                    ))}
                    <div className="budget-line">
                      <div><span>Activities</span><strong>{currency(activityTotal)}</strong></div>
                      <div className="progress-track"><div className="progress-fill activity-fill" style={{ width: `${Math.min(100, activityTotal / trip.budget_limit * 100)}%` }} /></div>
                    </div>
                  </div>
                </section>

                <section className="assistant-panel">
                  <div className="assistant-header">
                    <div className="assistant-avatar"><Sparkles size={20} /></div>
                    <div><h2>Travel copilot</h2><p><span className="status-dot" /> Ready to help</p></div>
                  </div>

                  <div className="assistant-message">
                    <div className="assistant-avatar small"><Sparkles size={16} /></div>
                    <div className="message-bubble">
                      <p>Your trip is ready to shape. Want to swap an activity or explore a cheaper alternative?</p>
                    </div>
                  </div>

                  {assistantReply && (
                    <div className="assistant-message">
                      <div className="assistant-avatar small"><Sparkles size={16} /></div>
                      <div className="message-bubble"><p>{assistantReply}</p></div>
                    </div>
                  )}

                  <div className="suggestion-chips">
                    <button onClick={() => setMessage("Visit a free local attraction")}>Free attractions</button>
                    <button onClick={() => setMessage("Find a cheaper activity")}>Save money</button>
                  </div>

                  {notice && <div className="notice">{notice}</div>}

                  {pendingAlternative && (
                    <div className="alternative-preview">
                      <div className="alternative-preview-top">
                        <span className="preview-label">PROPOSED CHANGE</span>
                        <span className={pendingAlternative.within_budget ? "budget-pill good" : "budget-pill bad"}>
                          {pendingAlternative.within_budget ? "Within budget" : "Over budget"}
                        </span>
                      </div>
                      <h3>{pendingAlternative.name}</h3>
                      <div className="preview-row"><span>Activity cost</span><strong>{currency(pendingAlternative.estimated_cost)}</strong></div>
                      <div className="preview-row"><span>New trip estimate</span><strong>{currency(pendingAlternative.estimated_total)}</strong></div>
                      <div className="preview-row">
                        <span>{pendingAlternative.within_budget ? "Budget remaining" : "Budget overrun"}</span>
                        <strong>{currency(pendingAlternative.within_budget ? pendingAlternative.remaining_budget : pendingAlternative.over_budget_by)}</strong>
                      </div>
                      <p className="preview-footnote">This replaces “{trip.activities[0]?.name}” on day {pendingAlternative.day}. Nothing changes until you approve.</p>
                    </div>
                  )}

                  <div className="chat-input">
                    <input value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Describe a change..." onKeyDown={(e) => { if (e.key === "Enter") void sendMessage(); }} />
                    <button onClick={() => void sendMessage()} disabled={loading || !message.trim()} title="Suggest alternative"><Send size={17} /></button>
                  </div>
                  <button className="apply-button" onClick={() => void applyAlternative()} disabled={loading || !pendingAlternative}>
                    {loading ? "Updating..." : "Approve and update itinerary"} <ArrowRight size={16} />
                  </button>
                  {pendingAlternative && (
                    <button className="cancel-alternative" onClick={() => { setPendingAlternative(null); setNotice("Proposed change discarded."); }} disabled={loading}>
                      Discard suggestion
                    </button>
                  )}
                  <p className="assistant-footnote">Prototype estimates only · No bookings are made</p>
                </section>
              </div>
            </>
          )}

          {notice && !trip && <div className="global-notice">{notice}</div>}

          <footer className="footer"><span>TripWise © 2026</span><span>Built for smarter travel decisions <Sparkles size={13} /></span></footer>
        </div>
      </section>
    </main>
  );
}

export default App;
