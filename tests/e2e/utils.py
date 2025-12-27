"""
Utility functions and classes for e2e tests.
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import websockets
from websockets.client import WebSocketClientProtocol


@dataclass
class GameSession:
    """Represents a game session for testing."""

    session_id: str
    websocket: Optional[WebSocketClientProtocol] = None
    messages: List[Dict[str, Any]] = field(default_factory=list)
    connected: bool = False
    player_name: Optional[str] = None

    async def connect(self, ws_url: str) -> None:
        """Connect to the WebSocket gateway."""
        self.websocket = await websockets.connect(f"{ws_url}")
        self.connected = True

        # Read welcome message
        msg = await self.recv_message()
        self.messages.append(msg)

    async def disconnect(self) -> None:
        """Disconnect from the WebSocket."""
        if self.websocket:
            await self.websocket.close()
            self.connected = False

    async def send_command(self, command: str) -> None:
        """Send a command to the game."""
        if not self.websocket:
            raise RuntimeError("Not connected")

        # Send as JSON message
        message = {
            "type": "command",
            "payload": {"raw": command}
        }
        await self.websocket.send(json.dumps(message))

    async def recv_message(self, timeout: float = 5.0) -> Dict[str, Any]:
        """Receive a message from the game."""
        if not self.websocket:
            raise RuntimeError("Not connected")

        try:
            raw = await asyncio.wait_for(self.websocket.recv(), timeout=timeout)
            return json.loads(raw)
        except asyncio.TimeoutError:
            return {"type": "timeout", "payload": {}}
        except json.JSONDecodeError:
            return {"type": "text", "payload": {"text": raw}}

    async def login(self, name: str, password: str = "test") -> str:
        """Login to the game and return the response."""
        await self.send_command(f"connect {name} {password}")

        # Collect responses until we get the room or error
        responses = []
        for _ in range(5):  # Max 5 messages
            msg = await self.recv_message(timeout=10.0)
            responses.append(msg)

            # Check if we got a room or error
            if msg.get("type") == "room":
                self.player_name = name
                break
            if msg.get("type") == "error":
                break
            if msg.get("type") == "text":
                text = msg.get("payload", {}).get("text", "")
                if "Welcome" in text or "created" in text.lower():
                    self.player_name = name
                    break

        # Return combined text
        texts = []
        for msg in responses:
            if msg.get("type") == "text":
                texts.append(msg.get("payload", {}).get("text", ""))
            elif msg.get("type") == "system":
                texts.append(msg.get("payload", {}).get("text", ""))

        return "\n".join(texts)

    async def send_and_wait(self, command: str, expected_type: str = "text", timeout: float = 5.0) -> Dict[str, Any]:
        """Send a command and wait for a specific response type."""
        await self.send_command(command)

        for _ in range(5):  # Max 5 messages
            msg = await self.recv_message(timeout=timeout)
            self.messages.append(msg)

            if msg.get("type") == expected_type:
                return msg
            if msg.get("type") == "error":
                return msg

        return {"type": "no_response", "payload": {}}


async def create_game_session(ws_url: str) -> GameSession:
    """Create and connect a game session."""
    session = GameSession(session_id="test")
    await session.connect(ws_url)
    return session


def get_text_from_response(response: Dict[str, Any]) -> str:
    """Extract text content from a response message."""
    if response.get("type") == "text":
        return response.get("payload", {}).get("text", "")
    if response.get("type") == "system":
        return response.get("payload", {}).get("text", "")
    if response.get("type") == "room":
        payload = response.get("payload", {})
        parts = [payload.get("name", ""), payload.get("description", "")]
        return "\n".join(p for p in parts if p)
    return ""


def assert_text_contains(response: Dict[str, Any], *substrings: str) -> None:
    """Assert that a response contains all given substrings."""
    text = get_text_from_response(response).lower()
    for substring in substrings:
        assert substring.lower() in text, f"Expected '{substring}' in response, got: {text[:200]}"


def assert_response_type(response: Dict[str, Any], expected_type: str) -> None:
    """Assert that a response has the expected type."""
    actual = response.get("type")
    assert actual == expected_type, f"Expected response type '{expected_type}', got '{actual}'"
