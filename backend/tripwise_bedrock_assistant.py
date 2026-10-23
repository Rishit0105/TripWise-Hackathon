"""TripWise conversational bridge: Amazon Bedrock Converse API -> TripWise MCP tools.

Run from the backend/project environment after starting mcp_server.py on port 8001:
    uvicorn tripwise_bedrock_assistant:app --host 127.0.0.1 --port 8002 --reload

AWS credentials are read through the standard boto3 credential chain. Never hard-code keys.
"""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = os.getenv("TRIPWISE_MCP_URL", "http://127.0.0.1:8001/mcp")
AWS_REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
MAX_TOOL_ROUNDS = 5

bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
app = FastAPI(title="TripWise Bedrock Assistant", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    trip_id: str | None = None
    trip_context: dict[str, Any] = Field(default_factory=dict)


def _mcp_result_to_json(result: Any) -> Any:
    """Normalize MCP result content to JSON-friendly data."""
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured
    content = getattr(result, "content", []) or []
    texts = [getattr(block, "text", "") for block in content if getattr(block, "text", None)]
    if len(texts) == 1:
        try:
            return json.loads(texts[0])
        except json.JSONDecodeError:
            return texts[0]
    return texts


def _schema_for_bedrock(tool: Any) -> dict[str, Any]:
    schema = getattr(tool, "inputSchema", None) or {"type": "object", "properties": {}}
    # Bedrock expects JSON Schema under inputSchema.json; MCP schemas are already JSON Schema.
    return {"toolSpec": {
        "name": tool.name,
        "description": (getattr(tool, "description", None) or f"TripWise MCP tool: {tool.name}")[:1024],
        "inputSchema": {"json": schema},
    }}


async def _run_chat(req: ChatRequest) -> dict[str, Any]:
    async with streamablehttp_client(MCP_URL) as (read_stream, write_stream, _get_session_id):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            listed = await session.list_tools()
            mcp_tools = listed.tools
            tool_lookup = {tool.name: tool for tool in mcp_tools}
            bedrock_tools = [_schema_for_bedrock(tool) for tool in mcp_tools]

            system_prompt = (
                "You are TripWise, a concise, friendly, Alexa+-style travel assistant. "
                "Use the TripWise MCP tools for facts about saved trips and budget calculations; "
                "never invent tool results, live prices, bookings, or confirmations. "
                "The user is chatting about a trip. Current trip context is supplied in the user message. "
                "For an alternative, call suggest_travel_alternatives with a real candidate and the current trip_id. "
                "Do not call replan_travel_activity unless the user explicitly asks to apply/commit a change. "
                "If the user requests a change but hasn't approved it, suggest and explain it rather than committing. "
                "When creating a trip, ask for any required missing values instead of inventing them. "
                "Be clear when costs are estimates."
            )
            context = {
                "trip_id": req.trip_id,
                "current_trip": req.trip_context,
                "user_message": req.message,
            }
            messages: list[dict[str, Any]] = [{
                "role": "user",
                "content": [{"text": json.dumps(context, ensure_ascii=False)}],
            }]
            executed: list[dict[str, Any]] = []

            for _ in range(MAX_TOOL_ROUNDS):
                response = bedrock.converse(
                    modelId=BEDROCK_MODEL_ID,
                    system=[{"text": system_prompt}],
                    messages=messages,
                    toolConfig={"tools": bedrock_tools},
                    inferenceConfig={"maxTokens": 700, "temperature": 0.3},
                )
                assistant_message = response["output"]["message"]
                messages.append(assistant_message)
                tool_uses = [block["toolUse"] for block in assistant_message.get("content", []) if "toolUse" in block]
                if not tool_uses:
                    reply = "\n".join(block.get("text", "") for block in assistant_message.get("content", []) if block.get("text"))
                    suggestion = None
                    # Expose the actual MCP alternative payload so the frontend can render its existing approval card.
                    for item in reversed(executed):
                        payload = item.get("result")
                        if item.get("tool") == "suggest_travel_alternatives" and isinstance(payload, dict):
                            alternatives = payload.get("alternatives") or payload.get("suggestions") or []
                            if alternatives and isinstance(alternatives[0], dict):
                                suggestion = alternatives[0]
                                break
                    return {"reply": reply or "I couldn't produce a response. Try rephrasing that.", "tool_calls": executed, "suggested_alternative": suggestion}

                tool_results = []
                for use in tool_uses:
                    name = use["name"]
                    args = use.get("input", {})
                    # Safety guard: frontend's approval button should be the commit boundary.
                    if name == "replan_travel_activity" and not any(
                        phrase in req.message.lower()
                        for phrase in ("apply this", "apply the change", "confirm the change", "commit the change", "yes, apply", "update the itinerary now")
                    ):
                        payload = {"error": "Change not applied. Ask the user to approve it in the TripWise UI first."}
                    elif name not in tool_lookup:
                        payload = {"error": f"Unknown TripWise tool: {name}"}
                    else:
                        # For current-trip operations, always bind to the trip currently selected in the UI.
                        if name in {"get_travel_trip", "replan_travel_activity", "suggest_travel_alternatives"} and req.trip_id:
                            args["trip_id"] = req.trip_id
                        try:
                            call_result = await session.call_tool(name, arguments=args)
                            payload = _mcp_result_to_json(call_result)
                            if getattr(call_result, "isError", False):
                                payload = {"error": payload}
                        except Exception as exc:
                            payload = {"error": f"MCP tool call failed: {exc}"}
                    executed.append({"tool": name, "arguments": args, "result": payload})
                    tool_results.append({
                        "toolResult": {
                            "toolUseId": use["toolUseId"],
                            "content": [{"json": payload if isinstance(payload, (dict, list, str, int, float, bool)) or payload is None else str(payload)}],
                            "status": "error" if isinstance(payload, dict) and "error" in payload else "success",
                        }
                    })
                messages.append({"role": "user", "content": tool_results})

            raise HTTPException(status_code=502, detail="Assistant reached its tool-call limit. Please simplify the request.")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model_id": BEDROCK_MODEL_ID, "mcp_url": MCP_URL, "region": AWS_REGION}


@app.post("/assistant/chat")
async def assistant_chat(req: ChatRequest) -> dict[str, Any]:
    try:
        return await _run_chat(req)
    except HTTPException:
        raise
    except (ClientError, BotoCoreError) as exc:
        code = getattr(exc, "response", {}).get("Error", {}).get("Code", "AWS_ERROR")
        if code in {"UnrecognizedClientException", "InvalidSignatureException", "NoCredentialsError"}:
            detail = "AWS credentials are not configured. Run `aws configure` or use an AWS IAM role, then retry."
        elif code in {"AccessDeniedException", "ResourceNotFoundException", "ValidationException"}:
            detail = f"Bedrock access/model configuration failed ({code}). Check the selected region, model access, and bedrock:InvokeModel permission."
        else:
            detail = f"Amazon Bedrock request failed ({code}): {exc}"
        raise HTTPException(status_code=502, detail=detail) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Assistant connection failed: {exc}") from exc
