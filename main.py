import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("voicemail-notification")
app = FastAPI()

# Temporary storage for testing.
# This resets whenever Render restarts or redeploys.
last_request: dict[str, Any] = {}


@app.get("/")
async def health_check() -> dict[str, str]:
    return {"status": "running"}


@app.get("/api/wxcc/last-payload")
async def view_last_payload() -> dict[str, Any]:
    """
    Temporary testing endpoint.

    Open this URL in a browser:
    https://YOUR-SERVICE.onrender.com/api/wxcc/last-payload
    """
    return last_request


@app.post("/api/wxcc/voicemail-transfer")
async def receive_voicemail_transfer(
    request: Request,
    interaction_id: str | None = Query(default=None, alias="interactionId"),
    caller_number: str | None = Query(default=None, alias="callerNumber"),
    dialed_number: str | None = Query(default=None, alias="dialedNumber"),
    queue_id: str | None = Query(default=None, alias="queueId"),
    queue_name: str | None = Query(default=None, alias="queueName"),
    voicemail_destination: str | None = Query(
        default=None,
        alias="voicemailDestination",
    ),
    voicemail_reason: str | None = Query(
        default=None,
        alias="voicemailReason",
    ),
    x_flow_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    global last_request

    expected_secret = os.getenv("FLOW_SHARED_SECRET")

    if expected_secret and x_flow_secret != expected_secret:
        raise HTTPException(
            status_code=401,
            detail="Invalid flow secret",
        )

    received_at = datetime.now(timezone.utc)

    # Read the body exactly as Flow Designer sent it.
    raw_body_bytes = await request.body()
    raw_body = raw_body_bytes.decode("utf-8", errors="replace")

    # Attempt to parse the body as JSON.
    parsed_payload: Any = None
    json_parse_error: str | None = None

    if raw_body.strip():
        try:
            parsed_payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            json_parse_error = str(exc)
    else:
        parsed_payload = None

    request_details = {
        "receivedAt": received_at.isoformat(),
        "queryParameters": {
            "interactionId": interaction_id,
            "callerNumber": caller_number,
            "dialedNumber": dialed_number,
            "queueId": queue_id,
            "queueName": queue_name,
            "voicemailDestination": voicemail_destination,
            "voicemailReason": voicemail_reason,
        },
        "contentType": request.headers.get("content-type"),
        "rawBody": raw_body,
        "parsedPayload": parsed_payload,
        "jsonParseError": json_parse_error,
    }

    last_request = request_details

    logger.info(
        "Voicemail transfer received | "
        "interaction=%s | caller=%s | dialed=%s | "
        "queueId=%s | queueName=%s | destination=%s | reason=%s",
        interaction_id,
        caller_number,
        dialed_number,
        queue_id,
        queue_name,
        voicemail_destination,
        voicemail_reason,
    )

    logger.info("Content-Type received: %s", request.headers.get("content-type"))
    logger.info("Raw request body: %s", raw_body)
    logger.info("Parsed JSON payload: %s", parsed_payload)

    # print() with flush=True makes the output especially easy to find in Render.
    print("FULL RAW BODY:", raw_body, flush=True)
    print("PARSED PAYLOAD:", parsed_payload, flush=True)

    if json_parse_error:
        logger.warning("JSON parsing failed: %s", json_parse_error)
        print("JSON PARSE ERROR:", json_parse_error, flush=True)

    agent_state_response = None

    if isinstance(parsed_payload, dict):
        agent_state_response = parsed_payload.get("agentStateResponse")
        logger.info("Agent-state response: %s", agent_state_response)
        print("AGENT-STATE RESPONSE:", agent_state_response, flush=True)

    return {
        "accepted": True,
        "interactionId": interaction_id,
        "callerNumber": caller_number,
        "queueName": queue_name,
        "receivedAt": received_at.isoformat(),
        "bodyReceived": bool(raw_body.strip()),
        "jsonParsed": parsed_payload is not None and json_parse_error is None,
        "agentStateResponseReceived": agent_state_response is not None,
        "jsonParseError": json_parse_error,
    }
