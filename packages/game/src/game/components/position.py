"""
Position Component

Tracks an entity's physical position/stance (standing, sitting, resting, sleeping).
This affects what commands they can use and their regeneration rates.
"""

from dataclasses import dataclass
from enum import Enum

from core import ComponentData


class Position(str, Enum):
    """Physical positions an entity can be in."""

    DEAD = "dead"
    SLEEPING = "sleeping"
    RESTING = "resting"
    SITTING = "sitting"
    STANDING = "standing"

    @classmethod
    def from_string(cls, value: str) -> "Position":
        """Convert string to Position, defaulting to STANDING."""
        try:
            return cls(value.lower())
        except ValueError:
            return cls.STANDING

    @classmethod
    def allows(cls, current: "Position", required: "Position") -> bool:
        """Check if current position allows an action requiring required position."""
        order = [cls.DEAD, cls.SLEEPING, cls.RESTING, cls.SITTING, cls.STANDING]
        return order.index(current) >= order.index(required)

    @property
    def regen_multiplier(self) -> float:
        """Get regeneration rate multiplier for this position."""
        multipliers = {
            Position.DEAD: 0.0,
            Position.SLEEPING: 3.0,  # Fastest regeneration
            Position.RESTING: 2.0,   # Good regeneration
            Position.SITTING: 1.5,   # Moderate regeneration
            Position.STANDING: 1.0,  # Normal regeneration
        }
        return multipliers.get(self, 1.0)

    @property
    def display_string(self) -> str:
        """Get display string for the position."""
        displays = {
            Position.DEAD: "dead",
            Position.SLEEPING: "sleeping",
            Position.RESTING: "resting",
            Position.SITTING: "sitting",
            Position.STANDING: "standing",
        }
        return displays.get(self, "standing")


@dataclass
class PositionData(ComponentData):
    """
    Tracks an entity's physical position/stance.

    Position affects:
    - What commands can be used (min_position on commands)
    - Regeneration rates (sleeping > resting > sitting > standing)
    - Combat engagement (combat interrupts rest/sleep)
    """

    position: Position = Position.STANDING

    # Furniture (optional - entity ID of what they're sitting/sleeping on)
    furniture_id: str = ""

    @property
    def is_standing(self) -> bool:
        """Check if entity is standing."""
        return self.position == Position.STANDING

    @property
    def is_resting(self) -> bool:
        """Check if entity is resting."""
        return self.position == Position.RESTING

    @property
    def is_sleeping(self) -> bool:
        """Check if entity is sleeping."""
        return self.position == Position.SLEEPING

    @property
    def is_sitting(self) -> bool:
        """Check if entity is sitting."""
        return self.position == Position.SITTING

    @property
    def is_incapacitated(self) -> bool:
        """Check if entity is sleeping or dead."""
        return self.position in (Position.SLEEPING, Position.DEAD)

    def stand(self) -> bool:
        """Stand up. Returns True if position changed."""
        if self.position == Position.STANDING:
            return False
        if self.position == Position.DEAD:
            return False
        self.position = Position.STANDING
        self.furniture_id = ""
        return True

    def sit(self, furniture_id: str = "") -> bool:
        """Sit down. Returns True if position changed."""
        if self.position == Position.DEAD:
            return False
        if self.position == Position.SITTING:
            return False
        self.position = Position.SITTING
        self.furniture_id = furniture_id
        return True

    def rest(self) -> bool:
        """Start resting. Returns True if position changed."""
        if self.position == Position.DEAD:
            return False
        if self.position == Position.RESTING:
            return False
        self.position = Position.RESTING
        return True

    def sleep(self) -> bool:
        """Go to sleep. Returns True if position changed."""
        if self.position == Position.DEAD:
            return False
        if self.position == Position.SLEEPING:
            return False
        self.position = Position.SLEEPING
        return True

    def wake(self) -> bool:
        """Wake up from sleep. Returns True if was sleeping."""
        if self.position != Position.SLEEPING:
            return False
        self.position = Position.RESTING  # Wake to resting, not standing
        return True

    def interrupt(self) -> bool:
        """
        Interrupt rest/sleep (e.g., combat starts).
        Returns True if position was interrupted.
        """
        if self.position in (Position.SLEEPING, Position.RESTING):
            self.position = Position.STANDING
            self.furniture_id = ""
            return True
        return False
