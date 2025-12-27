"""
Session Management

Handles player sessions, connection state, and reconnection logic.
"""

import uuid
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional
from datetime import datetime, timedelta
from enum import Enum

from core import EntityId

logger = logging.getLogger(__name__)


class SessionState(str, Enum):
    """Session connection states."""

    CONNECTED = "connected"  # Active connection
    LINKDEAD = "linkdead"  # Disconnected but can reconnect
    DISCONNECTED = "disconnected"  # Fully disconnected
    LOGIN = "login"  # In login process
    CHARACTER_SELECT = "character_select"
    CREATING_CHARACTER = "creating_character"


@dataclass
class Session:
    """
    Represents a player session.

    A session tracks the connection state and links to the player entity.
    Sessions persist briefly after disconnect to allow reconnection.
    """

    session_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)

    # Connection state
    state: SessionState = SessionState.LOGIN

    # Authentication
    account_id: Optional[str] = None
    username: Optional[str] = None

    # Character
    player_entity_id: Optional[EntityId] = None
    character_name: Optional[str] = None

    # WebSocket connection ID (opaque to this class)
    connection_id: Optional[str] = None

    # Reconnection
    reconnect_token: Optional[str] = None
    reconnect_expires: Optional[datetime] = None

    # Input history for arrow key recall
    command_history: list = field(default_factory=list)
    history_position: int = 0

    # Output buffering
    output_buffer: list = field(default_factory=list)

    @property
    def is_connected(self) -> bool:
        """Check if session has active connection."""
        return self.state == SessionState.CONNECTED

    @property
    def is_playing(self) -> bool:
        """Check if session is in-game with a character."""
        return self.state == SessionState.CONNECTED and self.player_entity_id is not None

    @property
    def is_linkdead(self) -> bool:
        """Check if session is linkdead (can reconnect)."""
        return self.state == SessionState.LINKDEAD

    @property
    def can_reconnect(self) -> bool:
        """Check if session can be reconnected."""
        if self.state != SessionState.LINKDEAD:
            return False
        if self.reconnect_expires and datetime.utcnow() > self.reconnect_expires:
            return False
        return True

    def mark_activity(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = datetime.utcnow()

    def mark_connected(self, connection_id: str) -> None:
        """Mark session as connected."""
        self.state = SessionState.CONNECTED
        self.connection_id = connection_id
        self.reconnect_token = None
        self.reconnect_expires = None
        self.mark_activity()

    def mark_linkdead(self, timeout_seconds: int = 300) -> str:
        """
        Mark session as linkdead.

        Returns a reconnect token for the client to use.
        """
        self.state = SessionState.LINKDEAD
        self.connection_id = None
        self.reconnect_token = uuid.uuid4().hex
        self.reconnect_expires = datetime.utcnow() + timedelta(seconds=timeout_seconds)
        return self.reconnect_token

    def mark_disconnected(self) -> None:
        """Mark session as fully disconnected."""
        self.state = SessionState.DISCONNECTED
        self.connection_id = None
        self.reconnect_token = None
        self.reconnect_expires = None

    def add_to_history(self, command: str) -> None:
        """Add command to history."""
        if command and (not self.command_history or self.command_history[-1] != command):
            self.command_history.append(command)
            # Limit history size
            if len(self.command_history) > 100:
                self.command_history = self.command_history[-100:]
        self.history_position = len(self.command_history)

    def get_history_previous(self) -> Optional[str]:
        """Get previous command from history."""
        if self.history_position > 0:
            self.history_position -= 1
            return self.command_history[self.history_position]
        return None

    def get_history_next(self) -> Optional[str]:
        """Get next command from history."""
        if self.history_position < len(self.command_history) - 1:
            self.history_position += 1
            return self.command_history[self.history_position]
        elif self.history_position == len(self.command_history) - 1:
            self.history_position = len(self.command_history)
            return ""
        return None

    def buffer_output(self, message: str) -> None:
        """Buffer output for when connection is restored."""
        self.output_buffer.append(message)
        # Limit buffer size
        if len(self.output_buffer) > 1000:
            self.output_buffer = self.output_buffer[-1000:]

    def flush_buffer(self) -> list:
        """Get and clear output buffer."""
        messages = self.output_buffer.copy()
        self.output_buffer.clear()
        return messages


class SessionManager:
    """
    Manages all active sessions.

    This is a simple in-memory implementation. For production,
    this would be backed by Redis for persistence across restarts.
    """

    def __init__(self):
        self._sessions: Dict[str, Session] = {}
        self._by_connection: Dict[str, str] = {}  # connection_id -> session_id
        self._by_player: Dict[str, str] = {}  # player_entity_id -> session_id
        self._by_account: Dict[str, str] = {}  # account_id -> session_id
        self._reconnect_tokens: Dict[str, str] = {}  # token -> session_id

    def create_session(self, connection_id: str) -> Session:
        """Create a new session for a connection."""
        session_id = uuid.uuid4().hex
        session = Session(
            session_id=session_id, connection_id=connection_id, state=SessionState.LOGIN
        )
        self._sessions[session_id] = session
        self._by_connection[connection_id] = session_id
        logger.info(f"Created session {session_id} for connection {connection_id}")
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """Get session by ID."""
        return self._sessions.get(session_id)

    def get_by_connection(self, connection_id: str) -> Optional[Session]:
        """Get session by connection ID."""
        session_id = self._by_connection.get(connection_id)
        if session_id:
            return self._sessions.get(session_id)
        return None

    def get_by_player(self, player_entity_id: EntityId) -> Optional[Session]:
        """Get session by player entity ID."""
        key = f"{player_entity_id.id}:{player_entity_id.entity_type}"
        session_id = self._by_player.get(key)
        if session_id:
            return self._sessions.get(session_id)
        return None

    def get_by_account(self, account_id: str) -> Optional[Session]:
        """Get session by account ID."""
        session_id = self._by_account.get(account_id)
        if session_id:
            return self._sessions.get(session_id)
        return None

    def get_by_reconnect_token(self, token: str) -> Optional[Session]:
        """Get session by reconnect token."""
        session_id = self._reconnect_tokens.get(token)
        if session_id:
            session = self._sessions.get(session_id)
            if session and session.can_reconnect:
                return session
        return None

    def bind_player(self, session: Session, player_entity_id: EntityId) -> None:
        """Bind a player entity to a session."""
        key = f"{player_entity_id.id}:{player_entity_id.entity_type}"
        session.player_entity_id = player_entity_id
        self._by_player[key] = session.session_id

    def bind_account(self, session: Session, account_id: str) -> None:
        """Bind an account to a session."""
        session.account_id = account_id
        self._by_account[account_id] = session.session_id

    def handle_disconnect(self, connection_id: str) -> Optional[Session]:
        """
        Handle connection disconnect.

        Returns the session if it was marked linkdead (can reconnect).
        """
        session = self.get_by_connection(connection_id)
        if not session:
            return None

        # Remove from connection index
        del self._by_connection[connection_id]

        # If playing, mark linkdead to allow reconnection
        if session.is_playing:
            token = session.mark_linkdead(timeout_seconds=300)
            self._reconnect_tokens[token] = session.session_id
            logger.info(f"Session {session.session_id} marked linkdead")
            return session

        # Otherwise, fully disconnect
        self._cleanup_session(session)
        return None

    def handle_reconnect(self, token: str, connection_id: str) -> Optional[Session]:
        """
        Handle reconnection attempt.

        Returns the session if reconnection was successful.
        """
        session = self.get_by_reconnect_token(token)
        if not session:
            return None

        # Clean up old token
        if session.reconnect_token:
            del self._reconnect_tokens[session.reconnect_token]

        # Restore connection
        session.mark_connected(connection_id)
        self._by_connection[connection_id] = session.session_id
        logger.info(f"Session {session.session_id} reconnected")
        return session

    def cleanup_expired(self) -> int:
        """
        Clean up expired linkdead sessions.

        Returns number of sessions cleaned up.
        """
        now = datetime.utcnow()
        to_cleanup = []

        for session_id, session in self._sessions.items():
            if session.state == SessionState.LINKDEAD:
                if session.reconnect_expires and now > session.reconnect_expires:
                    to_cleanup.append(session)

        for session in to_cleanup:
            self._cleanup_session(session)

        return len(to_cleanup)

    def _cleanup_session(self, session: Session) -> None:
        """Fully clean up a session."""
        session.mark_disconnected()

        # Remove from all indices
        if session.connection_id and session.connection_id in self._by_connection:
            del self._by_connection[session.connection_id]

        if session.player_entity_id:
            key = f"{session.player_entity_id.id}:{session.player_entity_id.entity_type}"
            if key in self._by_player:
                del self._by_player[key]

        if session.account_id and session.account_id in self._by_account:
            del self._by_account[session.account_id]

        if session.reconnect_token and session.reconnect_token in self._reconnect_tokens:
            del self._reconnect_tokens[session.reconnect_token]

        # Remove session itself
        if session.session_id in self._sessions:
            del self._sessions[session.session_id]

        logger.info(f"Session {session.session_id} cleaned up")

    def get_all_playing(self) -> list:
        """Get all sessions that are actively playing."""
        return [s for s in self._sessions.values() if s.is_playing]

    def get_stats(self) -> Dict[str, int]:
        """Get session statistics."""
        stats = {
            "total": len(self._sessions),
            "connected": 0,
            "linkdead": 0,
            "login": 0,
        }
        for session in self._sessions.values():
            if session.state == SessionState.CONNECTED:
                stats["connected"] += 1
            elif session.state == SessionState.LINKDEAD:
                stats["linkdead"] += 1
            elif session.state == SessionState.LOGIN:
                stats["login"] += 1
        return stats
