"""
Network Protocol

Defines message types and formats for client-server communication.

All messages are JSON-encoded with the structure:
{
    "type": "message_type",
    "payload": { ... }
}
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from enum import Enum
from datetime import datetime
import json


class MessageType(str, Enum):
    """Types of messages between client and server."""

    # Client -> Server
    COMMAND = "command"  # Player command input
    LOGIN = "login"  # Login request
    LOGOUT = "logout"  # Logout request
    PING = "ping"  # Keepalive ping
    CREATE_CHARACTER = "create_character"  # Character creation

    # Server -> Client
    TEXT = "text"  # Game text output
    PROMPT = "prompt"  # Command prompt
    ROOM = "room"  # Room description
    STATUS = "status"  # Status bar update (HP, mana, etc.)
    ERROR = "error"  # Error message
    PONG = "pong"  # Keepalive pong
    SYSTEM = "system"  # System message
    COMBAT = "combat"  # Combat update
    INVENTORY = "inventory"  # Inventory update
    MAP = "map"  # ASCII map data
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    DISCONNECT = "disconnect"


@dataclass
class Message:
    """Base message class."""

    type: MessageType
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        data = {
            "type": self.type.value,
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat(),
        }
        return json.dumps(data)

    @classmethod
    def from_json(cls, data: str) -> "Message":
        """Deserialize from JSON string."""
        parsed = json.loads(data)
        return cls(
            type=MessageType(parsed["type"]),
            payload=parsed.get("payload", {}),
            timestamp=(
                datetime.fromisoformat(parsed["timestamp"])
                if "timestamp" in parsed
                else datetime.utcnow()
            ),
        )


@dataclass
class CommandMessage:
    """Player command input."""

    raw: str  # Raw command text

    def to_message(self) -> Message:
        return Message(type=MessageType.COMMAND, payload={"raw": self.raw})


@dataclass
class LoginMessage:
    """Login request."""

    username: str
    password: str
    character_name: Optional[str] = None  # If selecting existing character

    def to_message(self) -> Message:
        return Message(
            type=MessageType.LOGIN,
            payload={
                "username": self.username,
                "password": self.password,
                "character_name": self.character_name,
            },
        )


@dataclass
class CreateCharacterMessage:
    """Character creation request."""

    name: str
    race: str = "human"
    class_name: str = "adventurer"

    def to_message(self) -> Message:
        return Message(
            type=MessageType.CREATE_CHARACTER,
            payload={
                "name": self.name,
                "race": self.race,
                "class_name": self.class_name,
            },
        )


@dataclass
class TextMessage:
    """Game text output."""

    text: str
    channel: str = "main"  # main, say, tell, shout, combat, system

    def to_message(self) -> Message:
        return Message(type=MessageType.TEXT, payload={"text": self.text, "channel": self.channel})


@dataclass
class PromptMessage:
    """Command prompt with status."""

    hp: int
    max_hp: int
    mana: int
    max_mana: int
    position: str = "standing"
    combat_target: Optional[str] = None

    def to_message(self) -> Message:
        return Message(
            type=MessageType.PROMPT,
            payload={
                "hp": self.hp,
                "max_hp": self.max_hp,
                "mana": self.mana,
                "max_mana": self.max_mana,
                "position": self.position,
                "combat_target": self.combat_target,
            },
        )


@dataclass
class RoomMessage:
    """Room description update."""

    name: str
    description: str
    exits: List[str]
    entities: List[Dict[str, str]]  # [{name, short_desc, type}, ...]
    items: List[Dict[str, str]]  # [{name, short_desc}, ...]

    def to_message(self) -> Message:
        return Message(
            type=MessageType.ROOM,
            payload={
                "name": self.name,
                "description": self.description,
                "exits": self.exits,
                "entities": self.entities,
                "items": self.items,
            },
        )


@dataclass
class StatusMessage:
    """Status bar update."""

    hp: int
    max_hp: int
    mana: int
    max_mana: int
    stamina: int
    max_stamina: int
    level: int
    experience: int
    experience_to_level: int
    gold: int

    def to_message(self) -> Message:
        return Message(type=MessageType.STATUS, payload=asdict(self))


@dataclass
class CombatMessage:
    """Combat update."""

    event: str  # hit, miss, death, flee
    attacker: str
    defender: str
    damage: int = 0
    message: str = ""

    def to_message(self) -> Message:
        return Message(type=MessageType.COMBAT, payload=asdict(self))


@dataclass
class ErrorMessage:
    """Error response."""

    error: str
    code: str = "error"

    def to_message(self) -> Message:
        return Message(type=MessageType.ERROR, payload={"error": self.error, "code": self.code})


@dataclass
class SystemMessage:
    """System notification."""

    text: str
    level: str = "info"  # info, warning, critical

    def to_message(self) -> Message:
        return Message(type=MessageType.SYSTEM, payload={"text": self.text, "level": self.level})


# ============================================================================
# Message Parsing
# ============================================================================


def parse_client_message(data: str) -> Optional[Message]:
    """Parse an incoming client message."""
    try:
        return Message.from_json(data)
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def create_text(text: str, channel: str = "main") -> str:
    """Create a text message JSON string."""
    return TextMessage(text=text, channel=channel).to_message().to_json()


def create_error(error: str, code: str = "error") -> str:
    """Create an error message JSON string."""
    return ErrorMessage(error=error, code=code).to_message().to_json()


def create_room(
    name: str,
    description: str,
    exits: List[str],
    entities: List[Dict[str, str]] = None,
    items: List[Dict[str, str]] = None,
) -> str:
    """Create a room message JSON string."""
    return (
        RoomMessage(
            name=name,
            description=description,
            exits=exits,
            entities=entities or [],
            items=items or [],
        )
        .to_message()
        .to_json()
    )
