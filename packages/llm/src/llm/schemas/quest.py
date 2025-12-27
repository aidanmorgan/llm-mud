"""
Quest Generation Schemas

Pydantic models for LLM-generated quest content.
"""

from enum import Enum
from typing import Dict, List, Optional, Literal, Tuple

from pydantic import BaseModel, Field

from .item import ItemRarity


class QuestArchetype(str, Enum):
    """Types of quests that can be generated."""

    COMBAT = "combat"  # Kill/defeat enemies
    EXPLORATION = "exploration"  # Discover locations
    GATHERING = "gathering"  # Collect items/resources
    DELIVERY = "delivery"  # Transport items between NPCs
    INVESTIGATION = "investigation"  # Talk to NPCs, find clues
    ESCORT = "escort"  # Protect/guide NPC
    DEFENSE = "defense"  # Defend location/NPC
    PUZZLE = "puzzle"  # Solve environmental puzzle
    RESCUE = "rescue"  # Free captured NPC/creature
    SABOTAGE = "sabotage"  # Destroy enemy resources


class ZoneType(str, Enum):
    """Zone environment types for theming."""

    CITY = "city"
    FOREST = "forest"
    DUNGEON = "dungeon"
    SWAMP = "swamp"
    MOUNTAIN = "mountain"
    RUINS = "ruins"
    COASTAL = "coastal"
    UNDERGROUND = "underground"
    VOLCANIC = "volcanic"
    FROZEN = "frozen"


# Zone theme -> preferred quest archetypes
ZONE_QUEST_PREFERENCES: Dict[str, List[QuestArchetype]] = {
    "city": [
        QuestArchetype.DELIVERY,
        QuestArchetype.INVESTIGATION,
        QuestArchetype.ESCORT,
    ],
    "forest": [
        QuestArchetype.GATHERING,
        QuestArchetype.EXPLORATION,
        QuestArchetype.RESCUE,
    ],
    "dungeon": [
        QuestArchetype.COMBAT,
        QuestArchetype.PUZZLE,
        QuestArchetype.SABOTAGE,
    ],
    "swamp": [
        QuestArchetype.GATHERING,
        QuestArchetype.RESCUE,
        QuestArchetype.INVESTIGATION,
    ],
    "mountain": [
        QuestArchetype.EXPLORATION,
        QuestArchetype.COMBAT,
        QuestArchetype.ESCORT,
    ],
    "ruins": [
        QuestArchetype.INVESTIGATION,
        QuestArchetype.PUZZLE,
        QuestArchetype.COMBAT,
    ],
    "coastal": [
        QuestArchetype.GATHERING,
        QuestArchetype.RESCUE,
        QuestArchetype.DELIVERY,
    ],
    "underground": [
        QuestArchetype.EXPLORATION,
        QuestArchetype.COMBAT,
        QuestArchetype.PUZZLE,
    ],
    "volcanic": [
        QuestArchetype.COMBAT,
        QuestArchetype.SABOTAGE,
        QuestArchetype.RESCUE,
    ],
    "frozen": [
        QuestArchetype.EXPLORATION,
        QuestArchetype.RESCUE,
        QuestArchetype.GATHERING,
    ],
}


class GeneratedReward(BaseModel):
    """Rewards for quest completion."""

    experience: int = Field(
        ..., ge=10, le=10000, description="Experience points awarded"
    )
    gold: int = Field(default=0, ge=0, le=5000, description="Gold pieces awarded")
    item_hints: List[str] = Field(
        default_factory=list,
        max_length=3,
        description="Descriptive hints for item rewards (e.g., 'a sturdy shield')",
    )
    reputation_faction: Optional[str] = Field(
        default=None, description="Faction that grants reputation"
    )
    reputation_amount: int = Field(
        default=0, ge=-100, le=100, description="Reputation change amount"
    )


class InstancedSpawn(BaseModel):
    """An entity that should be spawned just for this quest/player."""

    spawn_type: Literal["mob", "item", "npc"] = Field(
        ..., description="Type of entity to spawn"
    )
    template_hint: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="Base template or description for spawned entity",
    )
    spawn_location_hint: str = Field(
        ..., max_length=50, description="Where to spawn (room ID or description)"
    )
    custom_name: Optional[str] = Field(
        default=None, max_length=50, description="Custom name for spawned entity"
    )
    custom_description: Optional[str] = Field(
        default=None, max_length=200, description="Custom description for entity"
    )
    is_quest_target: bool = Field(
        default=True,
        description="If True, killing/collecting this completes objective",
    )


class GeneratedObjective(BaseModel):
    """Single quest objective with optional instanced spawns."""

    objective_type: Literal[
        "kill",
        "collect",
        "deliver",
        "explore",
        "talk",
        "use",
        "escort",
        "defend",
        "puzzle",
    ] = Field(..., description="Type of objective")
    description: str = Field(
        ...,
        min_length=10,
        max_length=150,
        description="Player-facing description of objective",
    )
    target_description: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="What player needs to find/kill/collect",
    )
    target_type_hint: str = Field(
        ...,
        min_length=2,
        max_length=30,
        description="Hint for target template matching (e.g., 'goblin', 'herb')",
    )
    required_count: int = Field(
        default=1,
        ge=1,
        le=10,
        description="How many needed (kept low to avoid grinds)",
    )
    location_hint: Optional[str] = Field(
        default=None, max_length=50, description="Where this objective takes place"
    )
    instanced_spawns: List[InstancedSpawn] = Field(
        default_factory=list,
        max_length=3,
        description="Entities to spawn just for this quest/player",
    )
    clue_text: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Clue or puzzle hint for investigation/puzzle quests",
    )


class GeneratedQuest(BaseModel):
    """Complete LLM-generated quest with narrative focus."""

    name: str = Field(
        ...,
        min_length=5,
        max_length=60,
        description="Evocative quest name (3-8 words)",
    )
    description: str = Field(
        ...,
        min_length=50,
        max_length=500,
        description="Full quest description telling a compelling story",
    )
    archetype: QuestArchetype = Field(..., description="Primary quest type")
    rarity: ItemRarity = Field(
        default=ItemRarity.COMMON, description="Quest importance/rarity"
    )
    objectives: List[GeneratedObjective] = Field(
        ...,
        min_length=1,
        max_length=5,
        description="Quest objectives to complete",
    )
    rewards: GeneratedReward = Field(..., description="Rewards for completion")
    intro_text: str = Field(
        ...,
        min_length=20,
        max_length=300,
        description="Text spoken by NPC when offering quest",
    )
    progress_text: str = Field(
        ...,
        min_length=10,
        max_length=200,
        description="Text when player returns with incomplete quest",
    )
    complete_text: str = Field(
        ...,
        min_length=20,
        max_length=300,
        description="Text when player completes the quest",
    )
    is_chain_quest: bool = Field(
        default=False, description="Whether this is part of a quest chain"
    )
    chain_position: int = Field(
        default=1, ge=1, le=10, description="Position in quest chain if applicable"
    )
    next_quest_hook: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Teaser text hinting at next quest in chain",
    )
    target_zones: List[str] = Field(
        default_factory=list,
        max_length=3,
        description="Zones where objectives take place",
    )


class ZoneQuestTheme(BaseModel):
    """Theme configuration for quest generation in a zone."""

    zone_id: str = Field(..., description="Zone identifier")
    zone_type: ZoneType = Field(..., description="Environment type of the zone")
    zone_name: str = Field(..., description="Display name of the zone")
    preferred_archetypes: List[QuestArchetype] = Field(
        default_factory=list, description="Quest types that fit this zone"
    )
    flavor_vocabulary: List[str] = Field(
        default_factory=list, description="Theme-appropriate words"
    )
    local_factions: List[str] = Field(
        default_factory=list, description="Factions present in this zone"
    )
    neighboring_zones: List[str] = Field(
        default_factory=list, description="Adjacent zones for cross-zone quests"
    )
    zone_description: str = Field(
        default="", max_length=500, description="Description of the zone atmosphere"
    )


class QuestGenerationContext(BaseModel):
    """Context provided to LLM for quest generation."""

    # Player info (CRITICAL for level scaling)
    player_level: int = Field(
        ..., ge=1, le=50, description="Player's current level - quests scale to this"
    )
    player_class: str = Field(..., description="Player's class")
    player_race: str = Field(..., description="Player's race")

    # Zone theme
    zone_theme: ZoneQuestTheme = Field(
        ..., description="Theme configuration for the zone"
    )
    target_zone_id: str = Field(
        ..., description="Zone where quest takes place (may differ from giver's zone)"
    )
    target_zone_name: str = Field(..., description="Display name of target zone")
    target_zone_description: str = Field(
        default="", max_length=500, description="Description of target zone"
    )

    # NPC giver
    giver_name: str = Field(..., description="Name of quest-giving NPC")
    giver_role: str = Field(
        default="quest giver", description="NPC's role (e.g., 'captain', 'merchant')"
    )
    giver_personality: Optional[str] = Field(
        default=None, description="NPC personality traits affecting dialogue"
    )
    giver_faction: Optional[str] = Field(
        default=None, description="Faction the NPC belongs to"
    )

    # Variety control
    recent_quest_types: List[QuestArchetype] = Field(
        default_factory=list, description="Recently completed quest types to avoid"
    )
    player_active_quest_count: int = Field(
        default=0, ge=0, description="Number of quests player currently has"
    )
    completed_quest_count: int = Field(
        default=0, ge=0, description="Total quests player has completed"
    )

    # Grounding (available targets in target zone)
    available_mob_types: List[str] = Field(
        default_factory=list,
        description="Mob types in zone (filtered to player_level +/- 3)",
    )
    available_locations: List[str] = Field(
        default_factory=list, description="Notable locations in zone"
    )
    available_item_types: List[str] = Field(
        default_factory=list, description="Item types that can be collected"
    )
    available_npcs: List[str] = Field(
        default_factory=list, description="NPCs that can be quest targets"
    )

    # Quality control
    avoid_simple_grinds: bool = Field(
        default=True,
        description="Prompt hint to avoid 'kill 10 X' style quests",
    )
    prefer_narrative: bool = Field(
        default=True, description="Prefer quests with story hooks"
    )

    # Level scaling
    target_difficulty: Literal["easy", "normal", "hard", "boss"] = Field(
        default="normal", description="Target difficulty relative to player level"
    )
    xp_multiplier: float = Field(
        default=1.0, ge=0.5, le=3.0, description="XP multiplier for events/bonuses"
    )
