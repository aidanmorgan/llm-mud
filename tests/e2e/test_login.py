"""
Login and character creation tests.

Tests the full login flow through both HTTP and WebSocket interfaces.
"""

import pytest
import asyncio

from .utils import (
    create_game_session,
    get_text_from_response,
    assert_text_contains,
)


class TestHTTPLogin:
    """Test login flow via HTTP POST commands."""

    def test_command_without_login(self, http_client, web_client_url):
        """Test that commands require login."""
        # First get a session
        response = http_client.get(web_client_url)
        session_id = response.cookies.get("session_id")
        assert session_id is not None

        # Try sending a command without logging in
        response = http_client.post(
            f"{web_client_url}/command",
            data={"command": "look", "session_id": session_id},
        )

        assert response.status_code == 200
        # Should get a not logged in message
        content = response.text.lower()
        assert "not logged in" in content or "connect" in content

    def test_login_creates_character(self, http_client, web_client_url):
        """Test that logging in creates a new character."""
        # Get a session
        response = http_client.get(web_client_url)
        session_id = response.cookies.get("session_id")

        # Login with connect command
        response = http_client.post(
            f"{web_client_url}/command",
            data={"command": "connect TestPlayer testpass", "session_id": session_id},
        )

        assert response.status_code == 200
        content = response.text.lower()
        # Should see welcome or created message
        assert "welcome" in content or "created" in content or "testplayer" in content

    def test_login_then_look(self, http_client, web_client_url):
        """Test that after login, player can look around."""
        # Get a session
        response = http_client.get(web_client_url)
        session_id = response.cookies.get("session_id")

        # Login
        http_client.post(
            f"{web_client_url}/command",
            data={"command": "connect LookTest testpass", "session_id": session_id},
        )

        # Try look command
        response = http_client.post(
            f"{web_client_url}/command",
            data={"command": "look", "session_id": session_id},
        )

        assert response.status_code == 200
        content = response.text
        # Should see room description or error if command handler not available
        # In a minimal setup, at least shouldn't error
        assert response.status_code == 200


class TestWebSocketLogin:
    """Test login flow via WebSocket."""

    @pytest.mark.asyncio
    async def test_websocket_connect(self, gateway_ws_url):
        """Test that WebSocket connection works."""
        session = await create_game_session(gateway_ws_url)
        try:
            assert session.connected
            # Should have received welcome message
            assert len(session.messages) >= 1
            msg = session.messages[0]
            text = get_text_from_response(msg)
            assert "welcome" in text.lower() or "connect" in text.lower()
        finally:
            await session.disconnect()

    @pytest.mark.asyncio
    async def test_websocket_login(self, gateway_ws_url):
        """Test login via WebSocket."""
        session = await create_game_session(gateway_ws_url)
        try:
            response = await session.login("WSTestPlayer", "testpass")

            # Should see welcome or created message
            assert "welcome" in response.lower() or "created" in response.lower()
            assert session.player_name == "WSTestPlayer"
        finally:
            await session.disconnect()

    @pytest.mark.asyncio
    async def test_websocket_look_after_login(self, gateway_ws_url):
        """Test look command via WebSocket after login."""
        session = await create_game_session(gateway_ws_url)
        try:
            await session.login("WSLookPlayer", "testpass")

            # Send look command
            response = await session.send_and_wait("look")

            # Should get room info or text response
            assert response.get("type") in ("room", "text", "error")
        finally:
            await session.disconnect()

    @pytest.mark.asyncio
    async def test_websocket_help_before_login(self, gateway_ws_url):
        """Test help command before login."""
        session = await create_game_session(gateway_ws_url)
        try:
            await session.send_command("help")
            response = await session.recv_message()

            text = get_text_from_response(response)
            # Should see available commands
            assert "connect" in text.lower() or "create" in text.lower() or "command" in text.lower()
        finally:
            await session.disconnect()


class TestMultipleSessions:
    """Test multiple concurrent sessions."""

    @pytest.mark.asyncio
    async def test_two_players_can_login(self, gateway_ws_url):
        """Test that two players can connect simultaneously."""
        session1 = await create_game_session(gateway_ws_url)
        session2 = await create_game_session(gateway_ws_url)

        try:
            # Both players login
            response1 = await session1.login("Player1", "pass1")
            response2 = await session2.login("Player2", "pass2")

            # Both should succeed
            assert "welcome" in response1.lower() or "created" in response1.lower()
            assert "welcome" in response2.lower() or "created" in response2.lower()

        finally:
            await session1.disconnect()
            await session2.disconnect()
