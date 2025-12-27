"""
Network Package

WebSocket server and session management for LLM-MUD.
"""

from .protocol import (
    Message,
    MessageType,
    parse_client_message,
    create_text,
    create_error,
    create_room,
    TextMessage,
    ErrorMessage,
    SystemMessage,
    PromptMessage,
    RoomMessage,
    StatusMessage,
    CombatMessage,
    CommandMessage,
    LoginMessage,
    CreateCharacterMessage,
)

from .session import (
    Session,
    SessionState,
    SessionManager,
)

from .gateway import (
    Gateway,
    get_gateway,
    start_gateway,
)

__all__ = [
    # Protocol
    "Message",
    "MessageType",
    "parse_client_message",
    "create_text",
    "create_error",
    "create_room",
    "TextMessage",
    "ErrorMessage",
    "SystemMessage",
    "PromptMessage",
    "RoomMessage",
    "StatusMessage",
    "CombatMessage",
    "CommandMessage",
    "LoginMessage",
    "CreateCharacterMessage",
    # Session
    "Session",
    "SessionState",
    "SessionManager",
    # Gateway
    "Gateway",
    "get_gateway",
    "start_gateway",
]
