"""Tests for nanoclaw-sidecar FastAPI application.

Tests follow TDD: written before implementation to define expected behaviour.
"""

import json
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture()
def groups_file(tmp_path: Path) -> Path:
    """Write a groups.json config and return its path."""
    data = {
        "dev": "123456789@g.us",
        "alerts": "987654321@g.us",
    }
    p = tmp_path / "groups.json"
    p.write_text(json.dumps(data))
    return p


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    """Create a nanoclaw DATA_DIR layout and return its path."""
    ipc_dir = tmp_path / "ipc" / "main" / "messages"
    ipc_dir.mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def app(groups_file: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Return the FastAPI app with env vars pointing at temp fixtures."""
    monkeypatch.setenv("NANOCLAW_DATA_DIR", str(data_dir))
    monkeypatch.setenv("GROUPS_CONFIG", str(groups_file))
    monkeypatch.setenv("DEFAULT_GROUP", "dev")

    # Import after env vars are set so module-level config picks them up.
    import importlib
    import src.main as m

    importlib.reload(m)
    return m.app


@pytest.fixture()
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


async def test_health_returns_ok(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


# ---------------------------------------------------------------------------
# POST /send — happy paths
# ---------------------------------------------------------------------------


async def test_send_writes_ipc_file_with_correct_format(
    client: AsyncClient, data_dir: Path
):
    resp = await client.post("/send", json={"message": "hello world", "group": "dev"})
    assert resp.status_code == 200

    messages_dir = data_dir / "ipc" / "main" / "messages"
    files = list(messages_dir.glob("webhook-*.json"))
    assert len(files) == 1

    payload = json.loads(files[0].read_text())
    assert payload["type"] == "message"
    assert payload["chatJid"] == "123456789@g.us"
    assert payload["text"] == "hello world"


async def test_send_uses_default_group_when_group_not_specified(
    client: AsyncClient, data_dir: Path
):
    resp = await client.post("/send", json={"message": "no group specified"})
    assert resp.status_code == 200

    messages_dir = data_dir / "ipc" / "main" / "messages"
    files = list(messages_dir.glob("webhook-*.json"))
    assert len(files) == 1

    payload = json.loads(files[0].read_text())
    assert payload["chatJid"] == "123456789@g.us"  # "dev" group JID


async def test_send_multiple_messages_create_separate_files(
    client: AsyncClient, data_dir: Path
):
    await client.post("/send", json={"message": "msg 1", "group": "dev"})
    await client.post("/send", json={"message": "msg 2", "group": "alerts"})

    messages_dir = data_dir / "ipc" / "main" / "messages"
    files = list(messages_dir.glob("webhook-*.json"))
    assert len(files) == 2


# ---------------------------------------------------------------------------
# POST /send — error paths
# ---------------------------------------------------------------------------


async def test_send_returns_404_for_unknown_group(client: AsyncClient):
    resp = await client.post("/send", json={"message": "hi", "group": "nonexistent"})
    assert resp.status_code == 404
    assert "nonexistent" in resp.json()["detail"]


async def test_send_requires_message_field(client: AsyncClient):
    resp = await client.post("/send", json={"group": "dev"})
    assert resp.status_code == 422


async def test_send_returns_503_when_ipc_dir_missing(
    groups_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """IPC messages dir doesn't exist — should return 503, not crash."""
    bad_data_dir = tmp_path / "no-ipc-here"
    bad_data_dir.mkdir()
    monkeypatch.setenv("NANOCLAW_DATA_DIR", str(bad_data_dir))
    monkeypatch.setenv("GROUPS_CONFIG", str(groups_file))
    monkeypatch.setenv("DEFAULT_GROUP", "dev")

    import importlib
    import src.main as m

    importlib.reload(m)

    async with AsyncClient(
        transport=ASGITransport(app=m.app), base_url="http://test"
    ) as c:
        resp = await c.post("/send", json={"message": "test", "group": "dev"})
    assert resp.status_code == 503
