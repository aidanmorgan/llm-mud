"""
Theme Constraint System

Themes define constraints and vocabulary for LLM-generated content.
Each portal or zone can have a theme that ensures thematic consistency.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DifficultyTier(str, Enum):
    """Difficulty tiers for content generation."""

    TRIVIAL = "trivial"  # Level 1-5
    EASY = "easy"  # Level 5-15
    MEDIUM = "medium"  # Level 15-30
    HARD = "hard"  # Level 30-50
    DEADLY = "deadly"  # Level 50+


@dataclass
class ThemeConstraints:
    """
    Constraints that shape LLM generation for a theme.

    These constraints are injected into prompts to ensure
    generated content matches the theme's style and setting.
    """

    # Vocabulary constraints
    allowed_mob_types: list[str] = field(default_factory=list)
    forbidden_mob_types: list[str] = field(default_factory=list)
    allowed_item_types: list[str] = field(default_factory=list)
    forbidden_item_types: list[str] = field(default_factory=list)

    # Descriptive vocabulary
    adjectives: list[str] = field(default_factory=list)
    nouns: list[str] = field(default_factory=list)
    verbs: list[str] = field(default_factory=list)
    forbidden_words: list[str] = field(default_factory=list)

    # Environmental constraints
    sector_types: list[str] = field(default_factory=list)
    weather_types: list[str] = field(default_factory=list)
    time_of_day: Optional[str] = None

    # Difficulty
    difficulty_tier: DifficultyTier = DifficultyTier.MEDIUM
    min_level: int = 1
    max_level: int = 100

    # Loot constraints
    loot_rarity_weights: dict[str, float] = field(default_factory=dict)
    gold_multiplier: float = 1.0

    def to_prompt_section(self) -> str:
        """Convert constraints to a prompt section for the LLM."""
        sections = []

        if self.allowed_mob_types:
            sections.append(f"Allowed creature types: {', '.join(self.allowed_mob_types)}")
        if self.forbidden_mob_types:
            sections.append(f"Do NOT use these creatures: {', '.join(self.forbidden_mob_types)}")

        if self.allowed_item_types:
            sections.append(f"Allowed item types: {', '.join(self.allowed_item_types)}")
        if self.forbidden_item_types:
            sections.append(f"Do NOT use these items: {', '.join(self.forbidden_item_types)}")

        if self.adjectives:
            sections.append(f"Preferred adjectives: {', '.join(self.adjectives)}")
        if self.nouns:
            sections.append(f"Preferred nouns: {', '.join(self.nouns)}")
        if self.forbidden_words:
            sections.append(f"Forbidden words: {', '.join(self.forbidden_words)}")

        if self.sector_types:
            sections.append(f"Environment types: {', '.join(self.sector_types)}")

        sections.append(f"Difficulty: {self.difficulty_tier.value}")
        sections.append(f"Level range: {self.min_level}-{self.max_level}")

        return "\n".join(sections)


@dataclass
class ThemeExamples:
    """Example content to guide LLM generation style."""

    room_examples: list[str] = field(default_factory=list)
    mob_examples: list[str] = field(default_factory=list)
    item_examples: list[str] = field(default_factory=list)

    def to_prompt_section(self) -> str:
        """Convert examples to a prompt section."""
        sections = []

        if self.room_examples:
            sections.append("Example room descriptions:")
            for ex in self.room_examples[:3]:
                sections.append(f"  - {ex}")

        if self.mob_examples:
            sections.append("Example mob descriptions:")
            for ex in self.mob_examples[:3]:
                sections.append(f"  - {ex}")

        if self.item_examples:
            sections.append("Example item descriptions:")
            for ex in self.item_examples[:3]:
                sections.append(f"  - {ex}")

        return "\n".join(sections)


@dataclass
class Theme:
    """
    A complete theme for content generation.

    Themes are typically associated with portals and define the style,
    vocabulary, and constraints for all content generated in that area.
    """

    theme_id: str
    name: str
    description: str

    # Core prompt elements
    setting_description: str = ""
    atmosphere: str = ""
    tone: str = "dark fantasy"

    # Constraints and examples
    constraints: ThemeConstraints = field(default_factory=ThemeConstraints)
    examples: ThemeExamples = field(default_factory=ThemeExamples)

    # Generation parameters
    temperature: float = 0.7
    creativity_level: str = "moderate"  # "conservative", "moderate", "creative"

    def build_system_prompt(self) -> str:
        """Build a system prompt incorporating the theme."""
        sections = [
            "You are a creative content generator for a fantasy MUD game.",
            "",
            f"## Theme: {self.name}",
            self.description,
            "",
        ]

        if self.setting_description:
            sections.append("## Setting")
            sections.append(self.setting_description)
            sections.append("")

        if self.atmosphere:
            sections.append("## Atmosphere")
            sections.append(self.atmosphere)
            sections.append("")

        sections.append("## Tone")
        sections.append(f"Write in a {self.tone} style.")
        sections.append("")

        sections.append("## Constraints")
        sections.append(self.constraints.to_prompt_section())
        sections.append("")

        if self.examples.room_examples or self.examples.mob_examples or self.examples.item_examples:
            sections.append("## Examples (match this style)")
            sections.append(self.examples.to_prompt_section())

        return "\n".join(sections)


# =============================================================================
# Predefined Themes
# =============================================================================


DARK_CAVE_THEME = Theme(
    theme_id="dark_cave",
    name="Dark Cave System",
    description="A network of underground caves filled with darkness and danger.",
    setting_description=(
        "Deep underground caverns carved by ancient waters. "
        "Stalactites drip with mineral-laden water. "
        "The air is damp and cold, smelling of earth and decay."
    ),
    atmosphere="Oppressive darkness, claustrophobic passages, echoing sounds.",
    tone="dark and foreboding",
    constraints=ThemeConstraints(
        allowed_mob_types=[
            "bat",
            "spider",
            "cave crawler",
            "blind fish",
            "mushroom creature",
            "cave troll",
            "darkness elemental",
            "crystal golem",
        ],
        forbidden_mob_types=["dragon", "unicorn", "phoenix", "angel"],
        adjectives=[
            "dark",
            "damp",
            "cold",
            "echoing",
            "crystalline",
            "jagged",
            "slippery",
            "ancient",
            "forgotten",
        ],
        nouns=[
            "stalactite",
            "stalagmite",
            "cavern",
            "tunnel",
            "crystal",
            "pool",
            "mushroom",
            "darkness",
        ],
        forbidden_words=["sunny", "bright", "cheerful", "pleasant", "meadow"],
        sector_types=["cave", "underground", "water_swim"],
        difficulty_tier=DifficultyTier.MEDIUM,
        min_level=10,
        max_level=30,
    ),
    examples=ThemeExamples(
        room_examples=[
            "A narrow passage opens into a vast cavern. Bioluminescent fungi cling to the walls.",
            "Water drips from unseen heights, pooling in shallow depressions on the stone floor.",
        ],
        mob_examples=[
            "A pale cave spider the size of a dog, its many eyes reflecting no light.",
            "A shambling fungal creature, spores drifting from its cap-like head.",
        ],
    ),
)


HAUNTED_RUINS_THEME = Theme(
    theme_id="haunted_ruins",
    name="Haunted Ruins",
    description="The crumbling remains of an ancient civilization, now haunted by the dead.",
    setting_description=(
        "Once-grand structures now lie in ruin, overgrown with twisted vines. "
        "The spirits of those who died here refuse to rest. "
        "Cold spots and unexplained sounds are common."
    ),
    atmosphere="Eerie, unsettling, frozen in time yet decaying.",
    tone="gothic horror",
    constraints=ThemeConstraints(
        allowed_mob_types=[
            "ghost",
            "skeleton",
            "wraith",
            "specter",
            "zombie",
            "poltergeist",
            "shadow",
            "banshee",
            "wight",
        ],
        forbidden_mob_types=["goblin", "orc", "dragon"],
        adjectives=[
            "crumbling",
            "ancient",
            "haunted",
            "spectral",
            "cold",
            "silent",
            "faded",
            "ethereal",
        ],
        nouns=[
            "ruins",
            "column",
            "archway",
            "tomb",
            "crypt",
            "statue",
            "altar",
            "shadows",
        ],
        forbidden_words=["warm", "cozy", "living", "modern", "cheerful"],
        sector_types=["inside", "city"],
        difficulty_tier=DifficultyTier.HARD,
        min_level=20,
        max_level=40,
    ),
    examples=ThemeExamples(
        room_examples=[
            "Broken columns line what was once a grand hall. Spectral lights flicker.",
            "A collapsed ceiling reveals the night sky. Cold mist clings to the floor.",
        ],
        mob_examples=[
            "A translucent figure in tattered noble garb, its face frozen in anguish.",
            "A skeleton in rusted armor, still clutching a notched blade.",
        ],
    ),
)


ENCHANTED_FOREST_THEME = Theme(
    theme_id="enchanted_forest",
    name="Enchanted Forest",
    description="A magical forest where the boundary between reality and fey is thin.",
    setting_description=(
        "Ancient trees with silver bark reach toward a sky of shifting colors. "
        "Flowers glow with inner light, and streams whisper secrets. "
        "The forest itself seems alive and aware of intruders."
    ),
    atmosphere="Mystical, dreamlike, beautiful yet dangerous.",
    tone="fairy tale with dark undertones",
    constraints=ThemeConstraints(
        allowed_mob_types=[
            "fey",
            "dryad",
            "sprite",
            "treant",
            "unicorn",
            "wolf",
            "giant spider",
            "pixie",
            "satyr",
            "nymph",
        ],
        forbidden_mob_types=["zombie", "skeleton", "robot", "demon"],
        adjectives=[
            "ancient",
            "mystical",
            "silver",
            "glowing",
            "twisted",
            "whispering",
            "enchanted",
            "wild",
        ],
        nouns=["tree", "flower", "stream", "moonlight", "moss", "vine", "glade", "mist"],
        forbidden_words=["dead", "rotting", "mechanical", "industrial", "urban"],
        sector_types=["forest", "field"],
        difficulty_tier=DifficultyTier.MEDIUM,
        min_level=15,
        max_level=35,
    ),
    examples=ThemeExamples(
        room_examples=[
            "A ring of ancient oaks surrounds a moonlit glade. Fireflies dance.",
            "Roots form a natural archway over a stream of silver water.",
        ],
        mob_examples=[
            "A beautiful dryad with bark-like skin and leaves for hair.",
            "A massive white stag with antlers that shimmer like starlight.",
        ],
    ),
)


# Registry of available themes
THEME_REGISTRY: dict[str, Theme] = {
    DARK_CAVE_THEME.theme_id: DARK_CAVE_THEME,
    HAUNTED_RUINS_THEME.theme_id: HAUNTED_RUINS_THEME,
    ENCHANTED_FOREST_THEME.theme_id: ENCHANTED_FOREST_THEME,
}


def get_theme(theme_id: str) -> Optional[Theme]:
    """Get a theme by ID."""
    return THEME_REGISTRY.get(theme_id)


def list_themes() -> list[str]:
    """List all available theme IDs."""
    return list(THEME_REGISTRY.keys())
