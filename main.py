import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()
logger = logging.getLogger("voicemail-notification")


class VoicemailTransferRequest(BaseModel):
    interaction_id: str = Field(alias="interactionId")
    caller_number: str | None = Field(default=None, alias="callerNumber")
    dialed_number: str | None = Field(default=None, alias="dialedNumber")
    queue_id: str | None = Field(default=None, alias="queueId")
    queue_name: str | None = Field(default=None, alias="queueName")
    voicemail_destination: str | None = Field(
        default=None,
        alias="voicemailDestination",
    )
    voicemail_reason: str | None = Field(
        default=None,
        alias="voicemailReason",
    )

    model_config = {
        "populate_by_name": True,
        "extra": "allow",
    }


@app.post("/api/wxcc/voicemail-transfer")
async def receive_voicemail_transfer(
    payload: VoicemailTransferRequest,
    x_flow_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    expected_secret = os.getenv("FLOW_SHARED_SECRET")

    if expected_secret and x_flow_secret != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid flow secret")

    received_at = datetime.now(timezone.utc)

    logger.info(
        "Voicemail transfer received: interaction=%s caller=%s queue=%s",
        payload.interaction_id,
        payload.caller_number,
        payload.queue_name,
    )

    # We will add the Webex Contact Center agent-state lookup here.
    # We will then send the notification email after capturing the snapshot.

    return {
        "accepted": True,
        "interactionId": payload.interaction_id,
        "receivedAt": received_at.isoformat(),
        "message": "Voicemail transfer notification accepted",
    }
