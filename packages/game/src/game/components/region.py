"""
Dynamic Region Components

Components for dynamic regions that seamlessly connect static areas.
Unlike portal-based instances, dynamic regions are part of the overworld
coordinate grid and generate rooms on-demand as players explore.

All configuration is loaded from YAML files.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from core import ComponentData

from .spatial import (
    Direction,
    RoomData,
    SectorType,
    PersistenceLevel,
    WorldCoordinate,
)


@dataclass
class RegionTheme:
    """
    Theme configuration for dynamic region LLM generation.

    All fields are loaded from YAML configuration files.
    Prompts use {placeholders} that are filled at generation time.
    """

    theme_id: str
    description: str = ""

    # LLM prompt templates with {placeholders}
    room_prompt: str = ""
    mob_prompt: str = ""
    item_prompt: str = ""

    # Vocabulary constraints for LLM
    vocabulary: List[str] = field(default_factory=list)
    forbidden_words: List[str] = field(default_factory=list)

    # Terrain constraints
    sector_types: List[SectorType] = field(default_factory=list)

    # Fallback templates if LLM unavailable
    mob_templates: List[str] = field(default_factory=list)
    item_templates: List[str] = field(default_factory=list)

    # Ambient messages for theme atmosphere
    ambient_messages: List[str] = field(default_factory=list)

    def format_room_prompt(
        self,
        adjacent_descriptions: str,
        required_exits: str,
        forbidden_exits: str,
        nearest_static: str,
        distance: int,
        coordinate: WorldCoordinate,
    ) -> str:
        """Format the room prompt with context placeholders."""
        return self.room_prompt.format(
            adjacent_descriptions=adjacent_descriptions,
            required_exits=required_exits,
            forbidden_exits=forbidden_exits,
            nearest_static=nearest_static,
            distance=distance,
            x=coordinate.x,
            y=coordinate.y,
            z=coordinate.z,
        )

    def format_mob_prompt(
        self,
        target_level: int,
        room_description: str,
    ) -> str:
        """Format the mob prompt with context placeholders."""
        return self.mob_prompt.format(
            target_level=target_level,
            room_description=room_description,
        )

    def format_item_prompt(
        self,
        target_level: int,
        target_rarity: str,
    ) -> str:
        """Format the item prompt with context placeholders."""
        return self.item_prompt.format(
            target_level=target_level,
            target_rarity=target_rarity,
        )


@dataclass
class RegionEndpoint:
    """Connection point between a dynamic region and a static area."""

    static_room_id: str  # Template ID of the static room
    direction: Direction  # Direction from static room into region
    coordinate: WorldCoordinate  # Coordinate of entry point in region


@dataclass
class RegionWaypoint:
    """Optional waypoint for guiding region generation paths."""

    coordinate: WorldCoordinate
    name: str = ""
    is_required: bool = True  # Must path pass through here?


@dataclass
class RegionGenerationConfig:
    """Configuration for how rooms are generated in a region."""

    min_rooms: int = 5
    max_rooms: int = 15
    difficulty_min: int = 1
    difficulty_max: int = 5
    mob_density: float = 0.3  # Probability of mob per room
    item_density: float = 0.1  # Probability of item per room
    branch_chance: float = 0.2  # Chance of side paths


@dataclass
class DynamicRegionData(ComponentData):
    """
    Defines a dynamic region that connects static areas.

    Loaded from YAML configuration files. The region stores its
    theme (including LLM prompts), endpoints, and generation config.
    """

    region_id: str = ""
    name: str = ""

    # Theme with embedded LLM prompts
    theme: Optional[RegionTheme] = None

    # Connection points to static areas
    endpoints: List[RegionEndpoint] = field(default_factory=list)

    # Optional waypoints for route planning
    waypoints: List[RegionWaypoint] = field(default_factory=list)

    # Generation configuration
    generation_config: RegionGenerationConfig = field(
        default_factory=RegionGenerationConfig
    )

    # Primary terrain type
    primary_sector_type: SectorType = SectorType.FOREST

    # Persistence level for generated rooms
    persistence_level: PersistenceLevel = PersistenceLevel.SESSION

    def get_endpoint_by_room(self, static_room_id: str) -> Optional[RegionEndpoint]:
        """Get endpoint configuration for a static room."""
        for endpoint in self.endpoints:
            if endpoint.static_room_id == static_room_id:
                return endpoint
        return None

    def get_endpoint_coordinates(self) -> Dict[str, WorldCoordinate]:
        """Get mapping of static room IDs to their region entry coordinates."""
        return {ep.static_room_id: ep.coordinate for ep in self.endpoints}


@dataclass
class RegionRoomData(RoomData):
    """
    A room within a dynamic region.

    Part of the overworld coordinate grid, not an isolated instance.
    Generated on-demand as players explore.
    """

    # Region identification
    region_id: str = ""
    coordinate: WorldCoordinate = field(default_factory=WorldCoordinate)

    # Connection to static areas (for edge rooms)
    connects_to_static: Optional[str] = None  # Static room template_id
    connects_direction: Optional[Direction] = None  # Direction to static area

    # Generation metadata
    generated_at: datetime = field(default_factory=datetime.utcnow)
    generation_seed: Optional[int] = None
    generation_context: str = ""  # What context prompted generation

    # Room state
    visited_by: Set[str] = field(default_factory=set)  # Player IDs who visited
    mobs_spawned: List[str] = field(default_factory=list)  # Mob entity IDs
    items_spawned: List[str] = field(default_factory=list)  # Item entity IDs

    def mark_visited(self, player_id: str) -> None:
        """Mark room as visited by a player."""
        self.visited_by.add(player_id)

    def was_visited_by(self, player_id: str) -> bool:
        """Check if player has visited this room."""
        return player_id in self.visited_by


@dataclass
class RegionState:
    """
    Runtime state for a dynamic region.

    Tracks generated rooms, coordinates, and room interconnections.
    Managed by the RegionManager actor.
    """

    region_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)

    # Generated rooms: coordinate tuple -> room entity ID
    rooms_by_coord: Dict[Tuple[int, int, int], str] = field(default_factory=dict)

    # Room count tracking
    rooms_generated: int = 0

    # Players currently in region
    players_in_region: Set[str] = field(default_factory=set)

    # Planned skeleton path (coordinates that must be navigable)
    skeleton_path: List[WorldCoordinate] = field(default_factory=list)

    def get_room_at(self, coord: WorldCoordinate) -> Optional[str]:
        """Get room entity ID at coordinate, if exists."""
        return self.rooms_by_coord.get((coord.x, coord.y, coord.z))

    def set_room_at(self, coord: WorldCoordinate, room_id: str) -> None:
        """Set room entity ID at coordinate."""
        self.rooms_by_coord[(coord.x, coord.y, coord.z)] = room_id
        self.rooms_generated += 1
        self.last_activity = datetime.utcnow()

    def has_room_at(self, coord: WorldCoordinate) -> bool:
        """Check if a room exists at coordinate."""
        return (coord.x, coord.y, coord.z) in self.rooms_by_coord

    def get_adjacent_rooms(
        self, coord: WorldCoordinate
    ) -> Dict[Direction, Optional[str]]:
        """Get all adjacent rooms to a coordinate."""
        result: Dict[Direction, Optional[str]] = {}
        for direction in Direction:
            neighbor = coord.neighbor(direction)
            result[direction] = self.get_room_at(neighbor)
        return result

    def player_enter(self, player_id: str) -> None:
        """Track player entering region."""
        self.players_in_region.add(player_id)
        self.last_activity = datetime.utcnow()

    def player_leave(self, player_id: str) -> None:
        """Track player leaving region."""
        self.players_in_region.discard(player_id)
        self.last_activity = datetime.utcnow()

    def is_empty(self) -> bool:
        """Check if no players are in the region."""
        return len(self.players_in_region) == 0
