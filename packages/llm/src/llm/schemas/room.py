"""
Room Generation Schemas

Pydantic models for LLM-generated room content.
"""

from enum import Enum
from typing import List, Optional, Literal

from pydantic import BaseModel, Field


class RoomExitDirection(str, Enum):
    """Valid directions for room exits."""

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


class SectorType(str, Enum):
    """Terrain/sector types for rooms."""

    INSIDE = "inside"
    CITY = "city"
    FIELD = "field"
    FOREST = "forest"
    HILLS = "hills"
    MOUNTAIN = "mountain"
    WATER_SWIM = "water_swim"
    WATER_NO_SWIM = "water_no_swim"
    UNDERWATER = "underwater"
    DESERT = "desert"
    CAVE = "cave"
    SWAMP = "swamp"
    AIR = "air"
    UNDERGROUND = "underground"


class GeneratedRoomExit(BaseModel):
    """Schema for a room exit."""

    direction: RoomExitDirection = Field(..., description="Direction of the exit")
    description: str = Field(
        ...,
        min_length=10,
        max_length=100,
        description="Brief description of what lies in that direction",
    )
    blocked: bool = Field(
        default=False, description="Whether the exit is currently blocked"
    )
    blocked_message: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Message shown when trying to use a blocked exit",
    )


class GeneratedRoom(BaseModel):
    """Schema for LLM-generated room content."""

    name: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="Short, evocative room name (3-6 words)",
    )
    short_description: str = Field(
        ...,
        min_length=10,
        max_length=100,
        description="One-line room summary shown in brief mode",
    )
    long_description: str = Field(
        ...,
        min_length=50,
        max_length=500,
        description="Full room description in second person ('You see...')",
    )
    exits: List[GeneratedRoomExit] = Field(
        ..., min_length=1, max_length=6, description="Available exits from this room"
    )
    ambient_messages: List[str] = Field(
        default_factory=list,
        max_length=5,
        description="Occasional flavor messages (1 in 10 chance to display)",
    )
    sector_type: SectorType = Field(
        ..., description="Terrain type affecting movement and abilities"
    )
    lighting: Literal["dark", "dim", "normal", "bright"] = Field(
        default="normal", description="Light level in the room"
    )
    danger_level: int = Field(
        ..., ge=1, le=10, description="Danger rating 1-10 affecting description tone"
    )
    has_water: bool = Field(default=False, description="Whether room contains water")
    indoors: bool = Field(default=False, description="Whether room is indoors")


class AdjacentRoomSummary(BaseModel):
    """Summary of an adjacent room for context."""

    name: str = Field(..., description="Name of the adjacent room")
    direction: RoomExitDirection = Field(
        ..., description="Direction to this room from current location"
    )
    sector_type: SectorType = Field(..., description="Terrain type of adjacent room")
    short_description: str = Field(
        ..., max_length=100, description="Brief description of adjacent room"
    )


class RegionTheme(BaseModel):
    """Theme information for a dynamic region."""

    name: str = Field(..., description="Region name")
    description: str = Field(..., description="Overall region theme description")
    vocabulary: List[str] = Field(
        default_factory=list, description="Encouraged vocabulary words"
    )
    forbidden_words: List[str] = Field(
        default_factory=list, description="Words to avoid"
    )
    primary_sector: SectorType = Field(
        default=SectorType.FOREST, description="Primary terrain type"
    )


class RoomGenerationContext(BaseModel):
    """Context provided to LLM for room generation."""

    region_theme: RegionTheme = Field(..., description="Theme of the containing region")
    adjacent_rooms: List[AdjacentRoomSummary] = Field(
        default_factory=list,
        max_length=6,
        description="Summaries of already-generated adjacent rooms",
    )
    required_exits: List[RoomExitDirection] = Field(
        ...,
        min_length=1,
        description="Exits that MUST be present in the generated room",
    )
    distance_from_entrance: int = Field(
        ..., ge=0, description="How many rooms from region entrance"
    )
    difficulty_target: int = Field(
        ..., ge=1, le=10, description="Target difficulty level for this room"
    )
    vocabulary_hints: List[str] = Field(
        default_factory=list,
        max_length=20,
        description="Theme-appropriate words to consider using",
    )
    forbidden_words: List[str] = Field(
        default_factory=list,
        max_length=20,
        description="Words that should not appear in descriptions",
    )
    sector_type_hint: SectorType = Field(
        default=SectorType.FOREST, description="Suggested terrain type"
    )
    existing_room_names: List[str] = Field(
        default_factory=list, description="Names already used in this region"
    )
    is_waypoint: bool = Field(
        default=False, description="Whether this is a named waypoint location"
    )
    waypoint_name: Optional[str] = Field(
        default=None, description="Name hint if this is a waypoint"
    )
