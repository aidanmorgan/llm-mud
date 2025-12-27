"""
Web Session Management

Manages HTTP sessions for web clients, tracking player state and
providing session persistence.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any
import logging

from core import EntityId

logger = logging.getLogger(__name__)


class WebSessionState(str, Enum):
    """State of a web session."""

    LOGIN = "login"  # Not logged in
    CREATING_CHARACTER = "creating_character"  # In character creation
    CONNECTED = "connected"  # Playing the game


@dataclass
class WebSession:
    """
    Represents a web client session.

    Tracks the connection between a browser session and a player entity.
    """

    session_id: str
    state: WebSessionState = WebSessionState.LOGIN
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)

    # Authentication
    account_id: Optional[str] = None
    username: Optional[str] = None

    # Player binding
    player_entity_id: Optional[EntityId] = None
    character_name: Optional[str] = None

    # Command history
    command_history: List[str] = field(default_factory=list)
    max_history: int = 100

    # WebSocket handler reference (not serialized)
    websocket_handler: Optional[Any] = None

    # Output buffer for messages when WebSocket disconnects
    output_buffer: List[str] = field(default_factory=list)
    max_buffer: int = 1000

    @property
    def is_authenticated(self) -> bool:
        """Check if the session is authenticated."""
        return self.account_id is not None

    @property
    def is_playing(self) -> bool:
        """Check if the session has a player in the game."""
        return self.player_entity_id is not None and self.state == WebSessionState.CONNECTED

    def mark_activity(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = datetime.utcnow()

    def add_to_history(self, command: str) -> None:
        """Add a command to history."""
        self.command_history.append(command)
        if len(self.command_history) > self.max_history:
            self.command_history.pop(0)

    def buffer_output(self, message: str) -> None:
        """Buffer output for later delivery."""
        self.output_buffer.append(message)
        if len(self.output_buffer) > self.max_buffer:
            self.output_buffer.pop(0)

    def get_buffered_output(self) -> List[str]:
        """Get and clear buffered output."""
        output = self.output_buffer.copy()
        self.output_buffer.clear()
        return output

    def set_websocket_handler(self, handler: Any) -> None:
        """Set the WebSocket handler for this session."""
        self.websocket_handler = handler

    def clear_websocket_handler(self) -> None:
        """Clear the WebSocket handler."""
        self.websocket_handler = None

    def is_expired(self, timeout_seconds: int = 3600) -> bool:
        """Check if session has expired due to inactivity."""
        cutoff = datetime.utcnow() - timedelta(seconds=timeout_seconds)
        return self.last_activity < cutoff


class WebSessionManager:
    """
    Manages web sessions.

    Handles session creation, lookup, and cleanup.
    In production, this would be backed by Redis or similar.
    """

    def __init__(self, session_timeout_seconds: int = 3600):
        self._sessions: Dict[str, WebSession] = {}
        self._account_sessions: Dict[str, str] = {}  # account_id -> session_id
        self._player_sessions: Dict[str, str] = {}  # player_entity_id str -> session_id
        self._session_timeout = session_timeout_seconds

    def create_session(self) -> WebSession:
        """Create a new session."""
        session_id = uuid.uuid4().hex
        session = WebSession(session_id=session_id)
        self._sessions[session_id] = session
        logger.debug(f"Created session: {session_id}")
        return session

    def get_session(self, session_id: str) -> Optional[WebSession]:
        """Get a session by ID."""
        session = self._sessions.get(session_id)
        if session:
            # Check for expiration
            if session.is_expired(self._session_timeout):
                self.destroy_session(session_id)
                return None
            session.mark_activity()
        return session

    def get_by_account(self, account_id: str) -> Optional[WebSession]:
        """Get session by account ID."""
        session_id = self._account_sessions.get(account_id)
        if session_id:
            return self.get_session(session_id)
        return None

    def get_by_player(self, player_entity_id: EntityId) -> Optional[WebSession]:
        """Get session by player entity ID."""
        key = str(player_entity_id)
        session_id = self._player_sessions.get(key)
        if session_id:
            return self.get_session(session_id)
        return None

    def bind_account(self, session: WebSession, account_id: str) -> None:
        """Bind an account to a session."""
        # Remove any existing binding for this account
        old_session_id = self._account_sessions.get(account_id)
        if old_session_id and old_session_id != session.session_id:
            # Kick the old session
            old_session = self._sessions.get(old_session_id)
            if old_session:
                old_session.account_id = None
                logger.info(f"Kicked old session for account {account_id}")

        session.account_id = account_id
        self._account_sessions[account_id] = session.session_id
        logger.debug(f"Bound account {account_id} to session {session.session_id}")

    def bind_player(self, session: WebSession, player_entity_id: EntityId) -> None:
        """Bind a player entity to a session."""
        key = str(player_entity_id)

        # Remove any existing binding for this player
        old_session_id = self._player_sessions.get(key)
        if old_session_id and old_session_id != session.session_id:
            old_session = self._sessions.get(old_session_id)
            if old_session:
                old_session.player_entity_id = None
                old_session.state = WebSessionState.LOGIN
                logger.info(f"Kicked old session for player {player_entity_id}")

        session.player_entity_id = player_entity_id
        self._player_sessions[key] = session.session_id
        session.state = WebSessionState.CONNECTED
        logger.debug(f"Bound player {player_entity_id} to session {session.session_id}")

    def destroy_session(self, session_id: str) -> None:
        """Destroy a session."""
        session = self._sessions.pop(session_id, None)
        if session:
            # Remove account mapping
            if session.account_id:
                if self._account_sessions.get(session.account_id) == session_id:
                    del self._account_sessions[session.account_id]

            # Remove player mapping
            if session.player_entity_id:
                key = str(session.player_entity_id)
                if self._player_sessions.get(key) == session_id:
                    del self._player_sessions[key]

            logger.debug(f"Destroyed session: {session_id}")

    def cleanup_expired(self) -> int:
        """Clean up expired sessions. Returns count of cleaned sessions."""
        expired = []
        for session_id, session in self._sessions.items():
            if session.is_expired(self._session_timeout):
                expired.append(session_id)

        for session_id in expired:
            self.destroy_session(session_id)

        if expired:
            logger.info(f"Cleaned up {len(expired)} expired sessions")

        return len(expired)

    def get_all_playing(self) -> List[WebSession]:
        """Get all sessions that are currently playing."""
        return [s for s in self._sessions.values() if s.is_playing]

    def get_stats(self) -> Dict[str, int]:
        """Get session statistics."""
        playing = sum(1 for s in self._sessions.values() if s.is_playing)
        authenticated = sum(1 for s in self._sessions.values() if s.is_authenticated)

        return {
            "total_sessions": len(self._sessions),
            "authenticated": authenticated,
            "playing": playing,
            "accounts_bound": len(self._account_sessions),
            "players_bound": len(self._player_sessions),
        }
