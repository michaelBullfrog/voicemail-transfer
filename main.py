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


def get_telephony_state(agent: dict[str, Any]) -> str:
    """
    Returns the agent's current telephony state.

    The Search API may return multiple chat and email channel records,
    so only the telephony channel is used for this notification.
    """
    channel_info = agent.get("channelInfo", [])

    if not isinstance(channel_info, list):
        return "unknown"

    for channel in channel_info:
        if not isinstance(channel, dict):
            continue

        channel_type = str(channel.get("channelType", "")).lower()

        if channel_type == "telephony":
            return str(channel.get("currentState", "unknown"))

    return "unknown"


def extract_agent_sessions(
    search_response_body: Any,
) -> list[dict[str, Any]]:
    """
    Extracts agentSessions from the Webex Contact Center Search API response.
    """
    if not isinstance(search_response_body, dict):
        return []

    data = search_response_body.get("data")

    if not isinstance(data, dict):
        return []

    agent_session = data.get("agentSession")

    if not isinstance(agent_session, dict):
        return []

    agent_sessions = agent_session.get("agentSessions", [])

    if not isinstance(agent_sessions, list):
        return []

    return [
        agent
        for agent in agent_sessions
        if isinstance(agent, dict)
    ]


def format_agents(
    agent_sessions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Converts the raw Search API agent-session records into a cleaner list.
    """
    formatted_agents: list[dict[str, Any]] = []

    for agent in agent_sessions:
        formatted_agents.append(
            {
                "agentId": agent.get("agentId"),
                "agentName": agent.get("agentName"),
                "teamId": agent.get("teamId"),
                "teamName": agent.get("teamName"),
                "isActive": bool(agent.get("isActive")),
                "telephonyState": get_telephony_state(agent),
            }
        )

    return formatted_agents


@app.get("/")
async def health_check() -> dict[str, str]:
    return {"status": "running"}


@app.get("/api/wxcc/last-payload")
async def view_last_payload() -> dict[str, Any]:
    """
    Temporary testing endpoint.

    Open:
    https://YOUR-SERVICE.onrender.com/api/wxcc/last-payload
    """
    return last_request


@app.post("/api/wxcc/voicemail-transfer")
async def receive_voicemail_transfer(
    request: Request,
    interaction_id: str | None = Query(
        default=None,
        alias="interactionId",
    ),
    caller_number: str | None = Query(
        default=None,
        alias="callerNumber",
    ),
    dialed_number: str | None = Query(
        default=None,
        alias="dialedNumber",
    ),
    queue_id: str | None = Query(
        default=None,
        alias="queueId",
    ),
    queue_name: str | None = Query(
        default=None,
        alias="queueName",
    ),
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
    raw_body = raw_body_bytes.decode(
        "utf-8",
        errors="replace",
    )

    parsed_payload: Any = None
    json_parse_error: str | None = None

    if raw_body.strip():
        try:
            parsed_payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            json_parse_error = str(exc)

    # Flow Designer is currently sending these values in the JSON body.
    # Use the body values when no query parameter was provided.
    if isinstance(parsed_payload, dict):
        interaction_id = (
            interaction_id
            or parsed_payload.get("interactionId")
        )
        caller_number = (
            caller_number
            or parsed_payload.get("callerNumber")
        )
        dialed_number = (
            dialed_number
            or parsed_payload.get("dialedNumber")
        )
        queue_id = (
            queue_id
            or parsed_payload.get("queueId")
        )
        queue_name = (
            queue_name
            or parsed_payload.get("queueName")
        )
        voicemail_destination = (
            voicemail_destination
            or parsed_payload.get("voicemailDestination")
        )
        voicemail_reason = (
            voicemail_reason
            or parsed_payload.get("voicemailReason")
        )

    search_status_code = None
    search_response_body: Any = None

    if isinstance(parsed_payload, dict):
        search_status_code = parsed_payload.get(
            "searchStatusCode"
        )
        search_response_body = parsed_payload.get(
            "searchResponseBody"
        )

    agent_sessions = extract_agent_sessions(
        search_response_body
    )

    formatted_agents = format_agents(
        agent_sessions
    )

    request_details = {
        "receivedAt": received_at.isoformat(),
        "interactionId": interaction_id,
        "callerNumber": caller_number,
        "dialedNumber": dialed_number,
        "queueId": queue_id,
        "queueName": queue_name,
        "voicemailDestination": voicemail_destination,
        "voicemailReason": voicemail_reason,
        "contentType": request.headers.get(
            "content-type"
        ),
        "searchStatusCode": search_status_code,
        "searchResponseBody": search_response_body,
        "agentCount": len(formatted_agents),
        "agents": formatted_agents,
        "rawBody": raw_body,
        "jsonParseError": json_parse_error,
    }

    last_request = request_details

    logger.info(
        "Voicemail transfer received | "
        "interaction=%s | caller=%s | dialed=%s | "
        "queueId=%s | queueName=%s | "
        "destination=%s | reason=%s",
        interaction_id,
        caller_number,
        dialed_number,
        queue_id,
        queue_name,
        voicemail_destination,
        voicemail_reason,
    )

    logger.info(
        "Search status code: %s",
        search_status_code,
    )

    logger.info(
        "Agent session count: %s",
        len(agent_sessions),
    )

    logger.info(
        "Formatted agents: %s",
        formatted_agents,
    )

    print(
        "FORMATTED AGENTS:",
        formatted_agents,
        flush=True,
    )

    if json_parse_error:
        logger.warning(
            "JSON parsing failed: %s",
            json_parse_error,
        )

    return {
        "accepted": True,
        "interactionId": interaction_id,
        "callerNumber": caller_number,
        "dialedNumber": dialed_number,
        "queueId": queue_id,
        "queueName": queue_name,
        "voicemailDestination": voicemail_destination,
        "voicemailReason": voicemail_reason,
        "receivedAt": received_at.isoformat(),
        "bodyReceived": bool(raw_body.strip()),
        "jsonParsed": (
            parsed_payload is not None
            and json_parse_error is None
        ),
        "searchStatusCode": search_status_code,
        "agentCount": len(formatted_agents),
        "agents": formatted_agents,
        "jsonParseError": json_parse_error,
    }
