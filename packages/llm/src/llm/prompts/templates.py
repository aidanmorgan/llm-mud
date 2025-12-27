"""
Prompt Templates for Content Generation

These builders construct prompts for generating rooms, mobs, items,
and dialogue within a given theme context.
"""

from dataclasses import dataclass, field
from typing import Optional

from ..theme import Theme
from ..schemas import ExitDirection


@dataclass
class RoomContext:
    """Context for generating a room."""

    # Connection context
    entrance_direction: Optional[ExitDirection] = None
    entrance_room_description: Optional[str] = None

    # Depth context
    depth_from_portal: int = 0
    max_depth: int = 10

    # Special requirements
    must_have_exits: list[ExitDirection] = field(default_factory=list)
    is_dead_end: bool = False
    is_boss_room: bool = False

    # Content hints
    feature_hints: list[str] = field(default_factory=list)


class RoomPromptBuilder:
    """Builds prompts for room generation."""

    def __init__(self, theme: Theme):
        self.theme = theme

    def build(self, context: Optional[RoomContext] = None) -> str:
        """Build a prompt for generating a room."""
        context = context or RoomContext()

        sections = ["Generate a room for a text-based MUD game."]

        # Entrance context
        if context.entrance_direction and context.entrance_room_description:
            opposite = self._opposite_direction(context.entrance_direction)
            sections.append(
                f"\nThe player enters from the {opposite.value}. "
                f"The previous room was: {context.entrance_room_description}"
            )

        # Depth context
        if context.depth_from_portal > 0:
            progress = context.depth_from_portal / context.max_depth
            if progress < 0.3:
                sections.append("\nThis is near the entrance - relatively safe.")
            elif progress < 0.7:
                sections.append("\nThis is deeper in - moderate danger level.")
            else:
                sections.append("\nThis is deep within - high danger, possibly climactic.")

        # Special room types
        if context.is_boss_room:
            sections.append(
                "\nThis is a BOSS ROOM - make it dramatic, spacious, and memorable. "
                "Include a notable feature that could serve as the boss's throne or lair."
            )
        elif context.is_dead_end:
            sections.append(
                "\nThis is a dead end - it should feel like a destination. "
                "Include something interesting: treasure, a secret, or a mystery."
            )

        # Required exits
        if context.must_have_exits:
            exits_str = ", ".join(e.value for e in context.must_have_exits)
            sections.append(f"\nMust include exits in these directions: {exits_str}")

        # Feature hints
        if context.feature_hints:
            sections.append(f"\nConsider including: {', '.join(context.feature_hints)}")

        # Theme constraints
        sections.append("\n## Requirements")
        sections.append(self.theme.constraints.to_prompt_section())

        return "\n".join(sections)

    def _opposite_direction(self, direction: ExitDirection) -> ExitDirection:
        opposites = {
            ExitDirection.NORTH: ExitDirection.SOUTH,
            ExitDirection.SOUTH: ExitDirection.NORTH,
            ExitDirection.EAST: ExitDirection.WEST,
            ExitDirection.WEST: ExitDirection.EAST,
            ExitDirection.UP: ExitDirection.DOWN,
            ExitDirection.DOWN: ExitDirection.UP,
        }
        return opposites[direction]


@dataclass
class MobContext:
    """Context for generating a mob."""

    # Location context
    room_description: Optional[str] = None
    room_atmosphere: Optional[str] = None

    # Difficulty context
    target_level: int = 10
    is_boss: bool = False
    is_miniboss: bool = False

    # Role hints
    role_hints: list[str] = field(default_factory=list)  # e.g., "guard", "merchant", "scout"

    # Pack context
    is_pack_leader: bool = False
    pack_size: int = 1


class MobPromptBuilder:
    """Builds prompts for mob generation."""

    def __init__(self, theme: Theme):
        self.theme = theme

    def build(self, context: Optional[MobContext] = None) -> str:
        """Build a prompt for generating a mob."""
        context = context or MobContext()

        sections = ["Generate a mob (creature/NPC) for a text-based MUD game."]

        # Location context
        if context.room_description:
            sections.append(f"\nThe mob is found in: {context.room_description}")

        # Difficulty
        sections.append(f"\nTarget level: {context.target_level}")

        if context.is_boss:
            sections.append(
                "\nThis is a BOSS mob - make it powerful, memorable, and unique. "
                "It should have special abilities and a distinctive personality. "
                "Scale health and damage significantly higher than normal mobs."
            )
        elif context.is_miniboss:
            sections.append(
                "\nThis is a MINIBOSS - stronger than normal but not as epic as a full boss. "
                "It should have at least one special ability."
            )

        # Role hints
        if context.role_hints:
            sections.append(f"\nThis mob's role: {', '.join(context.role_hints)}")

        # Pack context
        if context.pack_size > 1:
            if context.is_pack_leader:
                sections.append(
                    f"\nThis is the leader of a pack of {context.pack_size}. "
                    "Make it slightly stronger and more distinctive than the others."
                )
            else:
                sections.append(
                    f"\nThis mob is part of a pack of {context.pack_size}. "
                    "It should be appropriate for group combat."
                )

        # Theme constraints
        sections.append("\n## Requirements")
        sections.append(self.theme.constraints.to_prompt_section())

        return "\n".join(sections)


@dataclass
class ItemContext:
    """Context for generating an item."""

    # Source context
    dropped_by_mob: Optional[str] = None
    found_in_room: Optional[str] = None

    # Difficulty context
    target_level: int = 10
    target_rarity: str = "common"  # common, uncommon, rare, epic, legendary

    # Type hints
    preferred_type: Optional[str] = None  # weapon, armor, consumable, etc.
    preferred_slot: Optional[str] = None  # for equipment

    # Special flags
    is_quest_item: bool = False
    is_unique: bool = False


class ItemPromptBuilder:
    """Builds prompts for item generation."""

    def __init__(self, theme: Theme):
        self.theme = theme

    def build(self, context: Optional[ItemContext] = None) -> str:
        """Build a prompt for generating an item."""
        context = context or ItemContext()

        sections = ["Generate an item for a text-based MUD game."]

        # Source context
        if context.dropped_by_mob:
            sections.append(f"\nThis item is dropped by: {context.dropped_by_mob}")
        elif context.found_in_room:
            sections.append(f"\nThis item is found in: {context.found_in_room}")

        # Rarity and level
        sections.append(f"\nTarget level: {context.target_level}")
        sections.append(f"Target rarity: {context.target_rarity}")

        # Type hints
        if context.preferred_type:
            sections.append(f"\nPreferred item type: {context.preferred_type}")
        if context.preferred_slot:
            sections.append(f"Equipment slot: {context.preferred_slot}")

        # Special flags
        if context.is_unique:
            sections.append(
                "\nThis is a UNIQUE item - give it a proper name, history, "
                "and at least one special magical effect."
            )
        elif context.is_quest_item:
            sections.append(
                "\nThis is a QUEST item - it should be significant to the story "
                "and have distinctive lore. No combat stats needed."
            )

        # Rarity-based guidance
        rarity_guidance = {
            "common": "Simple and functional, no magical effects.",
            "uncommon": "Slightly better than average, may have one minor effect.",
            "rare": "Notably powerful with one significant magical effect.",
            "epic": "Very powerful with multiple effects or one major effect.",
            "legendary": "Exceptional power, unique history, multiple potent effects.",
        }
        if context.target_rarity in rarity_guidance:
            sections.append(f"\nRarity guidance: {rarity_guidance[context.target_rarity]}")

        # Theme constraints
        sections.append("\n## Requirements")
        sections.append(self.theme.constraints.to_prompt_section())

        return "\n".join(sections)


@dataclass
class DialogueContext:
    """Context for generating mob dialogue."""

    mob_name: str = ""
    mob_description: str = ""
    personality_traits: list[str] = field(default_factory=list)
    dialogue_style: str = ""
    role: str = ""  # e.g., "merchant", "quest_giver", "enemy"

    # Topics the mob should know about
    knowledge_topics: list[str] = field(default_factory=list)


class DialoguePromptBuilder:
    """Builds prompts for dialogue generation."""

    def __init__(self, theme: Theme):
        self.theme = theme

    def build(self, context: DialogueContext) -> str:
        """Build a prompt for generating dialogue."""
        sections = [
            "Generate dialogue options for an NPC in a text-based MUD game.",
            f"\nNPC: {context.mob_name}",
        ]

        if context.mob_description:
            sections.append(f"Description: {context.mob_description}")

        if context.personality_traits:
            sections.append(f"Personality: {', '.join(context.personality_traits)}")

        if context.dialogue_style:
            sections.append(f"Speaking style: {context.dialogue_style}")

        if context.role:
            sections.append(f"Role: {context.role}")

        if context.knowledge_topics:
            sections.append(
                f"\nThe NPC should have responses about: {', '.join(context.knowledge_topics)}"
            )

        sections.append(
            "\nGenerate natural-sounding dialogue that matches the personality. "
            "Include a greeting, farewell, and relevant topic responses."
        )

        return "\n".join(sections)
