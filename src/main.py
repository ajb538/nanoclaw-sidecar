"""nanoclaw-sidecar — HTTP to IPC bridge for nanoclaw WhatsApp bot.

Accepts POST /send requests from ai-orchestrator-mcp and writes nanoclaw
IPC files so the running nanoclaw container delivers the message to WhatsApp.

Environment variables:
    NANOCLAW_DATA_DIR   Path to nanoclaw's DATA_DIR shared volume.
    GROUPS_CONFIG       Path to groups.json (group name → WhatsApp JID).
    DEFAULT_GROUP       Group name to use when 'group' is omitted from request.
"""

import json
import os
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Configuration (read once at module level so reload() picks up new env vars)
# ---------------------------------------------------------------------------

_DATA_DIR = Path(os.environ.get("NANOCLAW_DATA_DIR", "/data"))
_GROUPS_CONFIG = Path(os.environ.get("GROUPS_CONFIG", "/config/groups.json"))
_DEFAULT_GROUP = os.environ.get("DEFAULT_GROUP", "")


def _load_groups() -> dict[str, str]:
    """Load group name → WhatsApp JID mapping from GROUPS_CONFIG file.

    Returns an empty dict if the file does not exist.
    """
    if not _GROUPS_CONFIG.exists():
        return {}
    return json.loads(_GROUPS_CONFIG.read_text())


_GROUPS: dict[str, str] = _load_groups()

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(title="nanoclaw-sidecar", version="1.0.0")


class SendRequest(BaseModel):
    """Request body for POST /send."""

    message: str
    group: str | None = None


@app.get("/health")
async def health() -> dict:
    """Health check endpoint.

    Returns:
        dict: {"ok": True}
    """
    return {"ok": True}


@app.post("/send")
async def send(req: SendRequest) -> dict:
    """Write a nanoclaw IPC message file to deliver a WhatsApp message.

    Args:
        req: SendRequest with message text and optional group name.

    Returns:
        dict: {"ok": True, "file": "<ipc-file-path>"}

    Raises:
        HTTPException 404: group name not found in groups.json.
        HTTPException 503: IPC messages directory does not exist.
    """
    group_name = req.group or _DEFAULT_GROUP

    jid = _GROUPS.get(group_name)
    if jid is None:
        raise HTTPException(
            status_code=404, detail=f"Group '{group_name}' not found in groups config"
        )

    ipc_dir = _DATA_DIR / "ipc" / "main" / "messages"
    if not ipc_dir.exists():
        raise HTTPException(
            status_code=503, detail="IPC messages directory does not exist"
        )

    filename = f"webhook-{int(time.time() * 1000)}.json"
    ipc_file = ipc_dir / filename

    payload = {"type": "message", "chatJid": jid, "text": req.message}
    ipc_file.write_text(json.dumps(payload))

    return {"ok": True, "file": str(ipc_file)}
