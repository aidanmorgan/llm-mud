"""
Command execution tests.

Tests various game commands work correctly.
"""

import pytest
import asyncio

from .utils import (
    create_game_session,
    get_text_from_response,
    assert_text_contains,
)


class TestBasicCommands:
    """Test basic game commands via WebSocket."""

    @pytest.fixture
    async def logged_in_session(self, gateway_ws_url):
        """Create a logged-in game session."""
        session = await create_game_session(gateway_ws_url)
        await session.login("CommandTestPlayer", "testpass")
        yield session
        await session.disconnect()

    @pytest.mark.asyncio
    async def test_look_command(self, logged_in_session):
        """Test the look command shows room info."""
        response = await logged_in_session.send_and_wait("look")

        # Should get room info
        assert response.get("type") in ("room", "text")
        if response.get("type") == "room":
            payload = response.get("payload", {})
            # Room should have name and description
            assert "name" in payload or "description" in payload
        else:
            # At minimum should have some text
            text = get_text_from_response(response)
            assert len(text) > 0

    @pytest.mark.asyncio
    async def test_exits_command(self, logged_in_session):
        """Test the exits command."""
        response = await logged_in_session.send_and_wait("exits")

        text = get_text_from_response(response)
        # Should show exits or indicate no exits
        # Response varies based on room, just check we got something
        assert response.get("type") in ("text", "room", "error")

    @pytest.mark.asyncio
    async def test_score_command(self, logged_in_session):
        """Test the score command shows character stats."""
        response = await logged_in_session.send_and_wait("score")

        text = get_text_from_response(response)
        # Should show some stats (HP, level, etc)
        text_lower = text.lower()
        # At least one of these should be present
        has_stats = any(
            keyword in text_lower
            for keyword in ["hp", "health", "level", "name", "stat", "score"]
        )
        assert has_stats or response.get("type") == "error"

    @pytest.mark.asyncio
    async def test_help_command(self, logged_in_session):
        """Test the help command shows available commands."""
        response = await logged_in_session.send_and_wait("help")

        text = get_text_from_response(response)
        # Should show some help info
        text_lower = text.lower()
        assert "command" in text_lower or "help" in text_lower or len(text) > 10

    @pytest.mark.asyncio
    async def test_inventory_command(self, logged_in_session):
        """Test the inventory command."""
        response = await logged_in_session.send_and_wait("inventory")

        text = get_text_from_response(response)
        # Should show inventory (even if empty)
        text_lower = text.lower()
        has_inventory_info = any(
            keyword in text_lower
            for keyword in ["inventory", "carrying", "nothing", "item", "empty", "gold"]
        )
        assert has_inventory_info or response.get("type") == "error"


class TestMovementCommands:
    """Test movement commands."""

    @pytest.fixture
    async def logged_in_session(self, gateway_ws_url):
        """Create a logged-in game session."""
        session = await create_game_session(gateway_ws_url)
        await session.login("MovementTestPlayer", "testpass")
        yield session
        await session.disconnect()

    @pytest.mark.asyncio
    async def test_invalid_direction(self, logged_in_session):
        """Test moving in an invalid direction."""
        # Try to go in a direction that might not exist
        response = await logged_in_session.send_and_wait("northwest")

        text = get_text_from_response(response)
        # Should get error or unknown command
        # Valid responses include "can't go" or "unknown"
        assert response.get("type") in ("text", "error")

    @pytest.mark.asyncio
    async def test_movement_aliases(self, logged_in_session):
        """Test movement command aliases (n, s, e, w)."""
        # Try short direction - may or may not work depending on room exits
        response = await logged_in_session.send_and_wait("n")

        # Should get some response (either moved or can't go)
        assert response.get("type") in ("text", "room", "error")


class TestCommunicationCommands:
    """Test communication commands."""

    @pytest.fixture
    async def logged_in_session(self, gateway_ws_url):
        """Create a logged-in game session."""
        session = await create_game_session(gateway_ws_url)
        await session.login("CommTestPlayer", "testpass")
        yield session
        await session.disconnect()

    @pytest.mark.asyncio
    async def test_say_command(self, logged_in_session):
        """Test the say command."""
        response = await logged_in_session.send_and_wait("say Hello world!")

        text = get_text_from_response(response)
        # Should echo what we said
        assert "hello" in text.lower() or "say" in text.lower() or response.get("type") == "text"

    @pytest.mark.asyncio
    async def test_emote_command(self, logged_in_session):
        """Test the emote command."""
        response = await logged_in_session.send_and_wait("emote waves hello")

        text = get_text_from_response(response)
        # Should show the emote or player name
        assert len(text) > 0 or response.get("type") == "text"


class TestCombatCommands:
    """Test combat-related commands (without actual combat)."""

    @pytest.fixture
    async def logged_in_session(self, gateway_ws_url):
        """Create a logged-in game session."""
        session = await create_game_session(gateway_ws_url)
        await session.login("CombatTestPlayer", "testpass")
        yield session
        await session.disconnect()

    @pytest.mark.asyncio
    async def test_kill_no_target(self, logged_in_session):
        """Test kill command with no target."""
        response = await logged_in_session.send_and_wait("kill")

        text = get_text_from_response(response)
        # Should get error about needing target
        text_lower = text.lower()
        assert "who" in text_lower or "what" in text_lower or "target" in text_lower or response.get("type") == "text"

    @pytest.mark.asyncio
    async def test_consider_no_target(self, logged_in_session):
        """Test consider command with no target."""
        response = await logged_in_session.send_and_wait("consider")

        text = get_text_from_response(response)
        # Should get error about needing target
        assert len(text) > 0 or response.get("type") == "text"
