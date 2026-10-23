"""TripWise conversational copilot with an optional OpenAI-compatible model.

The model proposes tool calls; deterministic planner functions calculate costs and
produce previews. No itinerary mutation occurs until the user approves it.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from database import get_trip
from planner import recommend_destination_activities, replan_activity

SYSTEM_PROMPT = """You are TripWise, a precise travel-planning copilot for trips in India.
Use tools for trip facts, activity options, and all budget calculations. Never invent
live prices, booking availability, or activity prices. Activity catalogue prices are
planning estimates, not live quotes. Do not claim a change was saved: preview_change
only creates a preview, and the user must approve it in the UI. If a request is not
about changing the itinerary, answer helpfully using the supplied trip facts. If the
user asks for a cheaper alternative, inspect destination activity options and preview
one suitable option. If the request is ambiguous about which activity to replace,
ask a brief clarification rather than guessing. Target indexes are zero-based; explain
which numbered activity is being proposed. Be concise and transparent about estimates."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_trip_summary",
            "description": "Get the saved trip, activity list, and calculated current budget totals.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_activity_options",
            "description": "Find destination-specific activity ideas and planning-estimate prices.",
            "parameters": {
                "type": "object",
                "properties": {
                    "interests": {"type": "array", "items": {"type": "string", "enum": ["adventure", "food", "nature", "culture"]}},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 15},
                },
                "required": ["interests", "limit"], "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "preview_change",
            "description": "Calculate a proposed replacement activity. Does not save the change. Use an activity name and cost returned by find_activity_options, or a user-provided explicit price.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_index": {"type": "integer", "minimum": 0},
                    "new_activity_name": {"type": "string"},
                    "new_activity_cost": {"type": "number", "minimum": 0},
                    "new_activity_day": {"type": "integer", "minimum": 1},
                },
                "required": ["target_index", "new_activity_name", "new_activity_cost", "new_activity_day"],
                "additionalProperties": False,
            },
        },
    },
]


def _trip_summary(trip: dict[str, Any]) -> dict[str, Any]:
    fixed_total = round(sum(float(value) for value in trip["fixed_costs"].values()), 2)
    activity_total = round(sum(float(a["estimated_cost"]) for a in trip["activities"]), 2)
    estimated_total = round(fixed_total + activity_total, 2)
    return {
        "trip": trip,
        "budget": {
            "fixed_total": fixed_total,
            "activity_total": activity_total,
            "estimated_total": estimated_total,
            "budget_limit": trip["budget_limit"],
            "remaining_budget": round(max(0, trip["budget_limit"] - estimated_total), 2),
            "over_budget_by": round(max(0, estimated_total - trip["budget_limit"]), 2),
            "within_budget": estimated_total <= trip["budget_limit"],
        },
    }


def _dispatch_tool(name: str, args: dict[str, Any], trip: dict[str, Any]) -> dict[str, Any]:
    if name == "get_trip_summary":
        return _trip_summary(trip)
    if name == "find_activity_options":
        return recommend_destination_activities(
            destination=trip["destination"],
            interests=args.get("interests", []),
            budget_per_person=trip["budget_limit"] / max(1, trip["travelers"]),
            limit=min(15, max(1, int(args.get("limit", 10)))),
        )
    if name == "preview_change":
        idx = int(args["target_index"])
        result = replan_activity(
            trip_days=trip["trip_days"], budget_limit=trip["budget_limit"],
            fixed_costs=trip["fixed_costs"], activities=trip["activities"],
            target_index=idx, new_activity_name=str(args["new_activity_name"]),
            new_activity_cost=float(args["new_activity_cost"]),
            new_activity_day=int(args["new_activity_day"]),
        )
        activity = result["activities"][idx]
        return {
            "target_index": idx,
            "alternative": {
                "name": activity["name"], "estimated_cost": activity["estimated_cost"],
                "day": activity["day"], "estimated_total": result["estimated_total"],
                "remaining_budget": result["remaining_budget"],
                "over_budget_by": result["over_budget_by"],
                "within_budget": result["within_budget"],
                "change_in_total": round(result["estimated_total"] - (sum(trip["fixed_costs"].values()) + sum(a["estimated_cost"] for a in trip["activities"])), 2),
            },
            "replaces": trip["activities"][idx]["name"],
        }
    return {"error": f"Unknown tool: {name}"}


def _fallback_reply(message: str, trip: dict[str, Any]) -> dict[str, Any]:
    """Useful no-key fallback; explicitly avoids claiming to be an LLM response."""
    lower = message.lower()
    summary = _trip_summary(trip)
    activities = trip["activities"]
    if any(term in lower for term in ("budget", "how much", "cost", "total", "remaining")):
        b = summary["budget"]
        reply = (f"Your current estimated trip total is ₹{b['estimated_total']:,.0f} against a "
                 f"₹{b['budget_limit']:,.0f} budget. "
                 + (f"That leaves ₹{b['remaining_budget']:,.0f}." if b["within_budget"] else f"You are ₹{b['over_budget_by']:,.0f} over budget.")
                 + " These are planning estimates, not confirmed bookings.")
        return {"reply": reply, "alternative": None, "target_index": None, "mode": "fallback"}

    explicit_price = re.search(r"(?:₹|\brs\.?\s*|\binr\s*)([\d,]+(?:\.\d{1,2})?)", message, re.I)
    cheaper = any(term in lower for term in ("cheaper", "save money", "budget-friendly", "budget friendly", "free attraction", "free activity", "free activities"))
    replacement = re.search(r"(?:replace|swap)\s+(?:activity\s+)?(\d+)", lower)
    target_index = int(replacement.group(1)) - 1 if replacement else 0
    if not activities:
        return {"reply": "This trip has no saved activities yet. Add activities to the itinerary first, then I can help replan it.", "alternative": None, "target_index": None, "mode": "fallback"}
    if target_index < 0 or target_index >= len(activities):
        return {"reply": f"I can see {len(activities)} activities. Tell me which activity number you want to replace (1–{len(activities)}).", "alternative": None, "target_index": None, "mode": "fallback"}

    if cheaper or "free" in lower:
        try:
            options = recommend_destination_activities(
                destination=trip["destination"], interests=["nature", "culture"],
                budget_per_person=trip["budget_limit"] / max(1, trip["travelers"]), limit=15,
            ).get("activities", [])
        except Exception:
            options = []
        current_name = activities[target_index]["name"].casefold()
        options = [o for o in options if o.get("name", "").casefold() != current_name]
        if "free" in lower:
            options = [o for o in options if o.get("estimated_cost") is not None and float(o["estimated_cost"]) == 0]
        else:
            options = [o for o in options if o.get("estimated_cost") is not None and float(o["estimated_cost"]) < float(activities[target_index]["estimated_cost"])]
        if options:
            chosen = min(options, key=lambda o: float(o.get("estimated_cost", 1e18)))
            args = {"target_index": target_index, "new_activity_name": chosen["name"], "new_activity_cost": float(chosen["estimated_cost"]), "new_activity_day": int(activities[target_index]["day"])}
            preview = _dispatch_tool("preview_change", args, trip)
            alt = preview["alternative"]
            return {"reply": f"I found {alt['name']} as an alternative for activity {target_index + 1}. Its ₹{alt['estimated_cost']:,.0f} cost is a catalogue planning estimate, not a live quote. Review the budget impact below; the itinerary will not change until you approve.", "alternative": alt, "target_index": target_index, "mode": "fallback"}
        return {"reply": f"I couldn't find a lower-cost catalogue activity for {trip['destination']} to replace activity {target_index + 1}. You can give me a specific activity and its price, or ask for general ideas.", "alternative": None, "target_index": None, "mode": "fallback"}

    if explicit_price:
        cost = float(explicit_price.group(1).replace(",", ""))
        name = re.sub(r"(?:₹|\brs\.?\s*|\binr\s*)[\d,]+(?:\.\d{1,2})?", "", message, flags=re.I).strip(" ,.!?")
        name = re.sub(r"^(?:replace|swap)(?:\s+activity\s+\d+)?\s+(?:with\s+)?", "", name, flags=re.I).strip()
        name = re.sub(r"\s+for\s*$", "", name, flags=re.I).strip()
        if name:
            preview = _dispatch_tool("preview_change", {"target_index": target_index, "new_activity_name": name, "new_activity_cost": cost, "new_activity_day": int(activities[target_index]["day"])}, trip)
            alt = preview["alternative"]
            return {"reply": f"Here's a budget preview for replacing activity {target_index + 1}. The price you supplied is treated as your estimate; nothing is saved until you approve.", "alternative": alt, "target_index": target_index, "mode": "fallback"}

    b = summary["budget"]
    activity_lines = "; ".join(f"{i + 1}. {a['name']} (Day {a['day']}, ₹{a['estimated_cost']:,.0f} estimate)" for i, a in enumerate(activities))
    return {"reply": f"Your {trip['destination']} trip has {trip['trip_days']} days for {trip['travelers']} traveller(s). Estimated total: ₹{b['estimated_total']:,.0f} of ₹{b['budget_limit']:,.0f}. Activities: {activity_lines}. You can ask me to find a cheaper or free alternative, or provide a replacement activity and its price.", "alternative": None, "target_index": None, "mode": "fallback"}


def chat_with_copilot(trip_id: str, message: str) -> dict[str, Any]:
    message = message.strip()
    if not message:
        raise ValueError("Message cannot be empty.")
    if len(message) > 2000:
        raise ValueError("Message must be 2,000 characters or fewer.")
    trip = get_trip(trip_id)
    if trip is None:
        raise LookupError("Trip not found.")

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return _fallback_reply(message, trip)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=os.getenv("OPENAI_BASE_URL") or None)
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({"message": message, "trip": _trip_summary(trip)}, ensure_ascii=False)},
        ]
        preview: dict[str, Any] | None = None
        for _ in range(5):
            response = client.chat.completions.create(model=model, messages=messages, tools=TOOLS, tool_choice="auto", temperature=0.2)
            choice = response.choices[0].message
            messages.append(choice.model_dump(exclude_none=True))
            if not choice.tool_calls:
                return {"reply": choice.content or "I couldn't formulate a response. Try rephrasing your request.", "alternative": preview["alternative"] if preview else None, "target_index": preview["target_index"] if preview else None, "mode": "ai", "model": model}
            for call in choice.tool_calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                    result = _dispatch_tool(call.function.name, args, trip)
                    if call.function.name == "preview_change" and "alternative" in result:
                        preview = result
                except Exception as exc:
                    result = {"error": str(exc)}
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)})
        return {"reply": "I reached the planning step limit. Please narrow the request and try again.", "alternative": preview["alternative"] if preview else None, "target_index": preview["target_index"] if preview else None, "mode": "ai", "model": model}
    except Exception as exc:
        # Keep the app usable when the model provider is unconfigured or temporarily unavailable.
        result = _fallback_reply(message, trip)
        result["provider_notice"] = f"AI provider unavailable; used built-in planning fallback ({type(exc).__name__})."
        return result
