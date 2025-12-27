"""
Spatial Components

Define where entities are and the structure of rooms/areas.

Enums:
- Direction: Movement directions
- SectorType: Room terrain/environment types
- RoomFlag: Boolean room properties
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from datetime import datetime
from enum import Enum, Flag, auto

from core import EntityId, ComponentData


class Direction(str, Enum):
    """Standard movement directions."""

    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"
    UP = "up"
    DOWN = "down"
    NORTHEAST = "northeast"
    NORTHWEST = "northwest"
    SOUTHEAST = "southeast"
    SOUTHWEST = "southwest"

    @classmethod
    def opposite(cls, direction: "Direction") -> "Direction":
        """Get the opposite direction."""
        opposites = {
            cls.NORTH: cls.SOUTH,
            cls.SOUTH: cls.NORTH,
            cls.EAST: cls.WEST,
            cls.WEST: cls.EAST,
            cls.UP: cls.DOWN,
            cls.DOWN: cls.UP,
            cls.NORTHEAST: cls.SOUTHWEST,
            cls.SOUTHWEST: cls.NORTHEAST,
            cls.NORTHWEST: cls.SOUTHEAST,
            cls.SOUTHEAST: cls.NORTHWEST,
        }
        return opposites.get(direction, direction)

    @classmethod
    def get_offset(cls, direction: "Direction") -> tuple[int, int, int]:
        """Get (x, y, z) offset for a direction."""
        offsets = {
            cls.NORTH: (0, 1, 0),
            cls.SOUTH: (0, -1, 0),
            cls.EAST: (1, 0, 0),
            cls.WEST: (-1, 0, 0),
            cls.UP: (0, 0, 1),
            cls.DOWN: (0, 0, -1),
            cls.NORTHEAST: (1, 1, 0),
            cls.NORTHWEST: (-1, 1, 0),
            cls.SOUTHEAST: (1, -1, 0),
            cls.SOUTHWEST: (-1, -1, 0),
        }
        return offsets.get(direction, (0, 0, 0))

    @classmethod
    def from_string(cls, s: str) -> Optional["Direction"]:
        """Parse direction from string, supporting abbreviations."""
        s = s.lower().strip()
        abbreviations = {
            "n": cls.NORTH,
            "north": cls.NORTH,
            "s": cls.SOUTH,
            "south": cls.SOUTH,
            "e": cls.EAST,
            "east": cls.EAST,
            "w": cls.WEST,
            "west": cls.WEST,
            "u": cls.UP,
            "up": cls.UP,
            "d": cls.DOWN,
            "down": cls.DOWN,
            "ne": cls.NORTHEAST,
            "northeast": cls.NORTHEAST,
            "nw": cls.NORTHWEST,
            "northwest": cls.NORTHWEST,
            "se": cls.SOUTHEAST,
            "southeast": cls.SOUTHEAST,
            "sw": cls.SOUTHWEST,
            "southwest": cls.SOUTHWEST,
        }
        return abbreviations.get(s)


class SectorType(str, Enum):
    """Room terrain/environment types affecting movement and combat."""

    INSIDE = "inside"
    CITY = "city"
    FIELD = "field"
    FOREST = "forest"
    HILLS = "hills"
    MOUNTAIN = "mountain"
    WATER_SHALLOW = "water_shallow"
    WATER_DEEP = "water_deep"
    UNDERWATER = "underwater"
    AIR = "air"
    DESERT = "desert"
    CAVE = "cave"
    SWAMP = "swamp"
    ROAD = "road"

    @property
    def movement_cost(self) -> int:
        """Get movement cost multiplier for this sector."""
        costs = {
            SectorType.INSIDE: 1,
            SectorType.CITY: 1,
            SectorType.ROAD: 1,
            SectorType.FIELD: 1,
            SectorType.FOREST: 2,
            SectorType.HILLS: 2,
            SectorType.MOUNTAIN: 3,
            SectorType.SWAMP: 3,
            SectorType.DESERT: 2,
            SectorType.CAVE: 2,
            SectorType.WATER_SHALLOW: 2,
            SectorType.WATER_DEEP: 4,
            SectorType.UNDERWATER: 3,
            SectorType.AIR: 1,
        }
        return costs.get(self, 1)

    @property
    def requires_swimming(self) -> bool:
        """Check if this sector requires swimming."""
        return self in (SectorType.WATER_DEEP, SectorType.UNDERWATER)

    @property
    def requires_flight(self) -> bool:
        """Check if this sector requires flight."""
        return self == SectorType.AIR


class PersistenceLevel(str, Enum):
    """How long generated content persists."""

    EPHEMERAL = "ephemeral"  # Disappears when last player leaves
    SESSION = "session"  # Lasts until server restart
    PERMANENT = "permanent"  # Saved to disk


@dataclass(frozen=True)
class WorldCoordinate:
    """
    3D world coordinate for tracking room positions.

    Used to prevent random maze generation and ensure proper
    interconnection of rooms in dynamic regions.

    Coordinate system:
    - x: East/West (East = positive)
    - y: North/South (North = positive)
    - z: Up/Down (Up = positive)
    """

    x: int = 0
    y: int = 0
    z: int = 0

    def neighbor(self, direction: Direction) -> "WorldCoordinate":
        """Get the coordinate in the given direction."""
        dx, dy, dz = Direction.get_offset(direction)
        return WorldCoordinate(self.x + dx, self.y + dy, self.z + dz)

    def distance_to(self, other: "WorldCoordinate") -> int:
        """Calculate Manhattan distance to another coordinate."""
        return abs(self.x - other.x) + abs(self.y - other.y) + abs(self.z - other.z)

    def direction_to(self, other: "WorldCoordinate") -> Optional[Direction]:
        """Get primary direction to another coordinate (None if same)."""
        dx = other.x - self.x
        dy = other.y - self.y
        dz = other.z - self.z

        if dx == 0 and dy == 0 and dz == 0:
            return None

        # Prioritize vertical movement
        if abs(dz) > 0 and abs(dz) >= max(abs(dx), abs(dy)):
            return Direction.UP if dz > 0 else Direction.DOWN

        # Prioritize cardinal over diagonal
        if abs(dx) > abs(dy):
            return Direction.EAST if dx > 0 else Direction.WEST
        elif abs(dy) > abs(dx):
            return Direction.NORTH if dy > 0 else Direction.SOUTH
        elif dx != 0 and dy != 0:
            # Diagonal
            if dx > 0 and dy > 0:
                return Direction.NORTHEAST
            elif dx > 0 and dy < 0:
                return Direction.SOUTHEAST
            elif dx < 0 and dy > 0:
                return Direction.NORTHWEST
            else:
                return Direction.SOUTHWEST

        return None

    def __str__(self) -> str:
        return f"({self.x}, {self.y}, {self.z})"

    def to_dict(self) -> Dict[str, int]:
        """Convert to dictionary for YAML serialization."""
        return {"x": self.x, "y": self.y, "z": self.z}

    @classmethod
    def from_dict(cls, data: Dict[str, int]) -> "WorldCoordinate":
        """Create from dictionary (YAML deserialization)."""
        return cls(
            x=data.get("x", 0),
            y=data.get("y", 0),
            z=data.get("z", 0),
        )


@dataclass
class ExitData:
    """Data for a room exit."""

    direction: Direction
    destination_id: Optional[EntityId] = None  # Room entity ID (None if unresolved/dynamic)
    description: str = ""
    is_door: bool = False
    is_locked: bool = False
    key_id: Optional[str] = None  # Template ID of key that opens this
    is_hidden: bool = False

    # Dynamic region fields - for exits that lead to/through dynamic regions
    leads_to_region: Optional[str] = None  # Region template_id (e.g., "forest_path")
    target_coordinate: Optional[WorldCoordinate] = None  # Target coordinate in region
    target_static_room: Optional[str] = None  # Or target static room template_id


@dataclass
class LocationData(ComponentData):
    """
    Where an entity currently is.

    Most mobile entities (players, mobs) have this component.
    """

    room_id: Optional[EntityId] = None

    # For finer positioning within a room (optional)
    x: float = 0.0
    y: float = 0.0

    # Track movement
    last_room_id: Optional[EntityId] = None
    entered_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RoomData(ComponentData):
    """
    Base room data - describes a location in the world.
    """

    short_description: str = "An empty room"
    long_description: str = "You see nothing special."

    # Exits: direction -> ExitData
    exits: Dict[str, ExitData] = field(default_factory=dict)

    # Room properties
    area_id: str = ""
    sector_type: SectorType = SectorType.INSIDE

    # Flags
    is_dark: bool = False
    is_safe: bool = False  # No combat allowed
    is_no_mob: bool = False  # Mobs can't enter
    is_no_recall: bool = False  # Can't teleport out
    is_no_magic: bool = False  # Magic doesn't work

    # Ambient messages shown periodically
    ambient_messages: List[str] = field(default_factory=list)

    def get_exit(self, direction: str) -> Optional[ExitData]:
        """Get exit data for a direction."""
        # Try exact match first
        if direction in self.exits:
            return self.exits[direction]

        # Try parsing as Direction enum
        dir_enum = Direction.from_string(direction)
        if dir_enum and dir_enum.value in self.exits:
            return self.exits[dir_enum.value]

        return None

    def get_available_exits(self) -> List[str]:
        """Get list of available exit directions."""
        return [d for d, exit_data in self.exits.items() if not exit_data.is_hidden]


@dataclass
class StaticRoomData(RoomData):
    """
    Room loaded from YAML definition.

    Static rooms are the "permanent" world that players explore.
    """

    template_id: str = ""
    zone_id: str = ""
    vnum: int = 0

    # Respawn configuration
    respawn_mobs: List[str] = field(default_factory=list)  # Template IDs
    respawn_items: List[str] = field(default_factory=list)  # Template IDs
    respawn_interval_s: int = 300  # 5 minutes default
    last_respawn: Optional[datetime] = None

    # Reset behavior
    reset_on_empty: bool = True  # Reset when no players present


@dataclass
class DynamicRoomData(RoomData):
    """
    LLM-generated room within a dynamic instance.
    """

    theme_id: str = ""
    instance_id: str = ""
    depth: int = 0  # Distance from instance entry

    # Generation metadata
    generated_at: datetime = field(default_factory=datetime.utcnow)
    generation_seed: Optional[int] = None

    # Persistence
    persistence_level: PersistenceLevel = PersistenceLevel.SESSION

    # Searchable/discoverable items
    searchable_items: List[str] = field(default_factory=list)
    searched_by: Set[str] = field(default_factory=set)  # Player IDs who searched

    def was_searched_by(self, player_id: str) -> bool:
        """Check if player already searched this room."""
        return player_id in self.searched_by

    def mark_searched(self, player_id: str) -> None:
        """Mark room as searched by player."""
        self.searched_by.add(player_id)
