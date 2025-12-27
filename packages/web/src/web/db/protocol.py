"""Database protocol and data models for player persistence."""

from typing import Protocol, Optional, List, Dict, Any, runtime_checkable
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PlayerAccount:
    """
    User account (email-based, can have multiple characters).

    Accounts are the authentication entity - players log in with
    email/password and then select a character to play.
    """

    account_id: str
    email: str
    password_hash: str
    created_at: datetime
    last_login: Optional[datetime] = None
    is_active: bool = True
    is_admin: bool = False

    # Account settings (shared across characters)
    settings: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PlayerCharacter:
    """
    A character belonging to an account.

    Characters are the in-game entity that players control.
    Each account can have multiple characters.
    """

    character_id: str
    account_id: str
    name: str
    race_id: str
    class_id: str
    level: int = 1
    experience: int = 0

    # Core stats (stored as dict for flexibility)
    stats: Dict[str, Any] = field(default_factory=dict)

    # Inventory and equipment (stored as lists/dicts)
    inventory: List[Dict[str, Any]] = field(default_factory=list)
    equipment: Dict[str, str] = field(default_factory=dict)

    # Location
    location_id: str = "ravenmoor_square"

    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_played: Optional[datetime] = None

    # Status flags
    is_active: bool = True
    is_deleted: bool = False

    # Gold and resources
    gold: int = 0

    # Quest progress (stored as dict)
    quest_log: Dict[str, Any] = field(default_factory=dict)

    # Preferences (character-specific)
    preferences: Dict[str, Any] = field(default_factory=dict)

    # Skills and abilities
    skills: Dict[str, int] = field(default_factory=dict)
    cooldowns: Dict[str, datetime] = field(default_factory=dict)


@runtime_checkable
class PlayerStore(Protocol):
    """
    Abstract player storage interface.

    Implementations can use SQLite (local), DynamoDB (AWS),
    or any other storage backend.
    """

    async def initialize(self) -> None:
        """Initialize the storage (create tables, etc.)."""
        ...

    # Account operations
    async def create_account(self, email: str, password: str) -> PlayerAccount:
        """
        Create a new account with hashed password.

        Raises ValueError if email already exists.
        """
        ...

    async def get_account(self, account_id: str) -> Optional[PlayerAccount]:
        """Get account by ID."""
        ...

    async def get_account_by_email(self, email: str) -> Optional[PlayerAccount]:
        """Look up account by email."""
        ...

    async def verify_password(
        self, email: str, password: str
    ) -> Optional[PlayerAccount]:
        """
        Verify credentials and return account if valid.

        Returns None if email not found or password incorrect.
        """
        ...

    async def update_account(self, account: PlayerAccount) -> None:
        """Update account data."""
        ...

    async def update_last_login(self, account_id: str) -> None:
        """Update the last login timestamp."""
        ...

    # Character operations
    async def create_character(
        self,
        account_id: str,
        name: str,
        race_id: str,
        class_id: str,
        starting_stats: Optional[Dict[str, Any]] = None,
        starting_location: str = "ravenmoor_square",
    ) -> PlayerCharacter:
        """
        Create a new character for an account.

        Raises ValueError if character name already exists.
        """
        ...

    async def get_character(self, character_id: str) -> Optional[PlayerCharacter]:
        """Get a character by ID."""
        ...

    async def get_character_by_name(self, name: str) -> Optional[PlayerCharacter]:
        """Get a character by name (case-insensitive)."""
        ...

    async def get_characters(self, account_id: str) -> List[PlayerCharacter]:
        """Get all characters for an account."""
        ...

    async def save_character(self, character: PlayerCharacter) -> None:
        """Save character state (on logout/periodic save)."""
        ...

    async def delete_character(self, character_id: str, soft: bool = True) -> bool:
        """
        Delete a character.

        If soft=True, marks as deleted but keeps data.
        If soft=False, permanently removes.

        Returns True if deleted.
        """
        ...

    async def character_name_exists(self, name: str) -> bool:
        """Check if character name is taken (case-insensitive)."""
        ...

    # Session/online tracking
    async def set_character_online(
        self, character_id: str, session_id: str
    ) -> None:
        """Mark character as online with session."""
        ...

    async def set_character_offline(self, character_id: str) -> None:
        """Mark character as offline."""
        ...

    async def get_online_characters(self) -> List[str]:
        """Get list of online character IDs."""
        ...

    async def is_character_online(self, character_id: str) -> bool:
        """Check if character is currently online."""
        ...
