import html
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
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


def format_notification_timestamp(received_at: datetime) -> str:
    """
    Converts the UTC received timestamp into the configured local timezone.

    Render environment variable example:
    MAIL_TIMEZONE=America/New_York
    """
    timezone_name = os.getenv(
        "MAIL_TIMEZONE",
        "America/New_York",
    )

    try:
        local_timezone = ZoneInfo(timezone_name)
    except Exception:
        logger.warning(
            "Invalid MAIL_TIMEZONE '%s'; using UTC.",
            timezone_name,
        )
        local_timezone = timezone.utc

    local_time = received_at.astimezone(local_timezone)

    return local_time.strftime(
        "%B %d, %Y at %I:%M:%S %p %Z"
    )


def get_telephony_state(agent: dict[str, Any]) -> str:
    channel_info = agent.get("channelInfo", [])

    if not isinstance(channel_info, list):
        return "Unknown"

    for channel in channel_info:
        if not isinstance(channel, dict):
            continue

        if str(channel.get("channelType", "")).lower() == "telephony":
            state = str(channel.get("currentState", "Unknown"))
            return state.replace("_", " ").title()

    return "Unknown"


def extract_agent_sessions(
    search_response_body: Any,
) -> list[dict[str, Any]]:
    if not isinstance(search_response_body, dict):
        return []

    sessions = (
        search_response_body
        .get("data", {})
        .get("agentSession", {})
        .get("agentSessions", [])
    )

    if not isinstance(sessions, list):
        return []

    return [
        agent
        for agent in sessions
        if isinstance(agent, dict)
    ]


def format_agents(
    agent_sessions: list[dict[str, Any]],
) -> list[dict[str, str]]:
    formatted_agents: list[dict[str, str]] = []

    for agent in agent_sessions:
        formatted_agents.append(
            {
                "agentName": str(
                    agent.get("agentName") or "Unknown Agent"
                ),
                "state": get_telephony_state(agent),
            }
        )

    return formatted_agents


def build_agent_table(
    agents: list[dict[str, str]],
) -> str:
    if not agents:
        return """
        <p>No active Contact Center agents were returned.</p>
        """

    rows = ""

    for agent in agents:
        agent_name = html.escape(agent["agentName"])
        state = html.escape(agent["state"])

        rows += f"""
        <tr>
            <td style="
                padding: 8px 12px;
                border: 1px solid #d9d9d9;
            ">
                {agent_name}
            </td>
            <td style="
                padding: 8px 12px;
                border: 1px solid #d9d9d9;
            ">
                {state}
            </td>
        </tr>
        """

    return f"""
    <table style="
        border-collapse: collapse;
        font-family: Arial, sans-serif;
        min-width: 360px;
    ">
        <thead>
            <tr>
                <th style="
                    padding: 8px 12px;
                    border: 1px solid #d9d9d9;
                    text-align: left;
                    background-color: #f2f2f2;
                ">
                    Agent
                </th>
                <th style="
                    padding: 8px 12px;
                    border: 1px solid #d9d9d9;
                    text-align: left;
                    background-color: #f2f2f2;
                ">
                    State
                </th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
    """


async def get_graph_access_token() -> str:
    tenant_id = os.getenv("MS_TENANT_ID")
    client_id = os.getenv("MS_CLIENT_ID")
    client_secret = os.getenv("MS_CLIENT_SECRET")

    if not tenant_id or not client_id or not client_secret:
        raise RuntimeError(
            "Microsoft Graph credentials are not configured."
        )

    token_url = (
        f"https://login.microsoftonline.com/"
        f"{tenant_id}/oauth2/v2.0/token"
    )

    token_data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            token_url,
            data=token_data,
        )

    if response.status_code != 200:
        logger.error(
            "Graph token request failed | status=%s | body=%s",
            response.status_code,
            response.text,
        )
        raise RuntimeError(
            "Unable to obtain Microsoft Graph access token."
        )

    token_payload = response.json()
    access_token = token_payload.get("access_token")

    if not access_token:
        raise RuntimeError(
            "Microsoft Graph did not return an access token."
        )

    return access_token


async def send_voicemail_email(
    caller_number: str | None,
    agents: list[dict[str, str]],
    received_at: datetime,
) -> None:
    sender = os.getenv("MAIL_SENDER")
    recipient = os.getenv("MAIL_RECIPIENT")

    if not sender or not recipient:
        raise RuntimeError(
            "MAIL_SENDER and MAIL_RECIPIENT must be configured."
        )

    access_token = await get_graph_access_token()

    caller_display = html.escape(
        caller_number or "Unknown caller"
    )

    timestamp_display = html.escape(
        format_notification_timestamp(received_at)
    )

    agent_table = build_agent_table(agents)

    subject = f"Call transferred to voicemail - {caller_display}"

    email_body = f"""
    <html>
        <body style="
            font-family: Arial, sans-serif;
            color: #222222;
        ">
            <h2>Call Transferred to Voicemail</h2>

            <p>
                <strong>Caller:</strong>
                {caller_display}
            </p>

            <p>
                <strong>Timestamp:</strong>
                {timestamp_display}
            </p>

            <p>
                Contact Center agent states at the time
                of the voicemail transfer:
            </p>

            {agent_table}
        </body>
    </html>
    """

    graph_url = (
        "https://graph.microsoft.com/v1.0/"
        f"users/{sender}/sendMail"
    )

    graph_payload = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": email_body,
            },
            "toRecipients": [
                {
                    "emailAddress": {
                        "address": recipient,
                    }
                }
            ],
        },
        "saveToSentItems": True,
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            graph_url,
            headers=headers,
            json=graph_payload,
        )

    if response.status_code != 202:
        logger.error(
            "Graph sendMail failed | status=%s | body=%s",
            response.status_code,
            response.text,
        )
        raise RuntimeError(
            f"Microsoft Graph sendMail failed with "
            f"status {response.status_code}."
        )

    logger.info(
        "Voicemail email accepted by Microsoft Graph | "
        "sender=%s | recipient=%s | timestamp=%s",
        sender,
        recipient,
        timestamp_display,
    )


@app.get("/")
async def health_check() -> dict[str, str]:
    return {"status": "running"}


@app.get("/api/wxcc/last-payload")
async def view_last_payload() -> dict[str, Any]:
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
    timestamp_display = format_notification_timestamp(received_at)

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

    if json_parse_error:
        logger.error(
            "Invalid JSON received from Flow Designer: %s",
            json_parse_error,
        )
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON request body.",
        )

    if not isinstance(parsed_payload, dict):
        raise HTTPException(
            status_code=400,
            detail="A JSON object is required.",
        )

    interaction_id = (
        interaction_id
        or parsed_payload.get("interactionId")
    )

    caller_number = (
        caller_number
        or parsed_payload.get("callerNumber")
    )

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

    last_request = {
        "receivedAtUtc": received_at.isoformat(),
        "receivedAtLocal": timestamp_display,
        "interactionId": interaction_id,
        "callerNumber": caller_number,
        "searchStatusCode": search_status_code,
        "agentCount": len(formatted_agents),
        "agents": formatted_agents,
    }

    logger.info(
        "Voicemail notification received | "
        "interaction=%s | caller=%s | agents=%s | timestamp=%s",
        interaction_id,
        caller_number,
        len(formatted_agents),
        timestamp_display,
    )

    try:
        await send_voicemail_email(
            caller_number=caller_number,
            agents=formatted_agents,
            received_at=received_at,
        )
    except RuntimeError as exc:
        logger.exception(
            "Unable to send voicemail notification email."
        )

        # Return 200 so the caller still continues to voicemail.
        return {
            "accepted": True,
            "emailSent": False,
            "emailError": str(exc),
            "interactionId": interaction_id,
            "agentCount": len(formatted_agents),
            "timestamp": timestamp_display,
        }

    return {
        "accepted": True,
        "emailSent": True,
        "interactionId": interaction_id,
        "callerNumber": caller_number,
        "agentCount": len(formatted_agents),
        "agents": formatted_agents,
        "receivedAt": received_at.isoformat(),
        "timestamp": timestamp_display,
    }
