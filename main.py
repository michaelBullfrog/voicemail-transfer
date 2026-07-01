import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import Body, FastAPI, Header, HTTPException, Query

app = FastAPI()
logger = logging.getLogger("voicemail-notification")


@app.get("/")
async def health_check() -> dict[str, str]:
    return {"status": "running"}


@app.post("/api/wxcc/voicemail-transfer")
async def receive_voicemail_transfer(
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
    payload: dict[str, Any] | None = Body(default=None),
    x_flow_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    expected_secret = os.getenv("FLOW_SHARED_SECRET")

    if expected_secret and x_flow_secret != expected_secret:
        raise HTTPException(
            status_code=401,
            detail="Invalid flow secret",
        )

    received_at = datetime.now(timezone.utc)

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

    logger.info("Full JSON payload from Flow Designer: %s", payload)

    if payload:
        logger.info(
            "Agent-state response: %s",
            payload.get("agentStateResponse"),
        )

    return {
        "accepted": True,
        "interactionId": interaction_id,
        "callerNumber": caller_number,
        "queueName": queue_name,
        "receivedAt": received_at.isoformat(),
        "payloadReceived": payload is not None,
    }
