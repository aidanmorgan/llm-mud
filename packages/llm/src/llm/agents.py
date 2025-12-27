"""
PydanticAI Agents for Content Generation

Specialized agents for generating different types of game content
with structured, type-safe outputs.

Usage:
    from llm.agents import room_agent, mob_agent

    # Generate a room with context
    result = await room_agent.run(
        "Generate a forest clearing",
        deps=context
    )
    room = result.data  # GeneratedRoom instance
"""

import logging
import os
from typing import Optional

from pydantic_ai import Agent, RunContext

from .schemas import (
    # Room
    GeneratedRoom,
    RoomGenerationContext,
    GeneratedMob,
    MobGenerationContext,
    # Item
    GeneratedItem,
    ItemGenerationContext,
    # Combat
    CombatNarration,
    CombatNarrationContext,
    # Dialogue
    DialogueResponse,
    DialogueContext,
    # Quest
    GeneratedQuest,
    QuestGenerationContext,
    QuestArchetype,
    ZoneQuestTheme,
    # Crafting
    GeneratedCraftedItem,
    CraftingContext,
    ComponentQuality,
)
from .prompts.system import (
    ROOM_SYSTEM_PROMPT,
    MOB_SYSTEM_PROMPT,
    ITEM_SYSTEM_PROMPT,
    COMBAT_SYSTEM_PROMPT,
    DIALOGUE_SYSTEM_PROMPT,
    QUEST_SYSTEM_PROMPT,
    CRAFTING_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Model Configuration
# =============================================================================

def get_default_model() -> str:
    """Get the default model from environment or fallback."""
    return os.environ.get(
        "LLM_MODEL",
        "anthropic:claude-3-5-sonnet-20241022"
    )


def get_fast_model() -> str:
    """Get a faster model for simpler tasks."""
    return os.environ.get(
        "LLM_FAST_MODEL",
        "anthropic:claude-3-5-haiku-20241022"
    )


# =============================================================================
# Room Generation Agent
# =============================================================================

room_agent: Agent[RoomGenerationContext, GeneratedRoom] = Agent(
    get_default_model(),
    result_type=GeneratedRoom,
    deps_type=RoomGenerationContext,
    system_prompt=ROOM_SYSTEM_PROMPT,
)


@room_agent.system_prompt
def room_dynamic_prompt(ctx: RunContext[RoomGenerationContext]) -> str:
    """Add dynamic context to room generation prompt."""
    deps = ctx.deps

    sections = []

    # Region theme
    sections.append(f"Region: {deps.region_theme.name}")
    sections.append(f"Theme: {deps.region_theme.description}")

    # Vocabulary guidance
    if deps.vocabulary_hints:
        vocab = ", ".join(deps.vocabulary_hints[:15])
        sections.append(f"Encouraged vocabulary: {vocab}")

    if deps.forbidden_words:
        forbidden = ", ".join(deps.forbidden_words[:10])
        sections.append(f"Avoid these words: {forbidden}")

    # Adjacent room context
    if deps.adjacent_rooms:
        adj_names = [r.name for r in deps.adjacent_rooms]
        sections.append(f"Adjacent rooms: {', '.join(adj_names)}")

    # Required exits
    if deps.required_exits:
        exits = [e.value for e in deps.required_exits]
        sections.append(f"MUST include exits: {', '.join(exits)}")

    # Difficulty
    sections.append(f"Danger level: {deps.difficulty_target}/10")

    # Sector type
    sections.append(f"Terrain type: {deps.sector_type_hint.value}")

    # Waypoint
    if deps.is_waypoint and deps.waypoint_name:
        sections.append(f"This is a waypoint called: {deps.waypoint_name}")

    # Avoid duplicate names
    if deps.existing_room_names:
        sections.append(
            f"Avoid these names (already used): {', '.join(deps.existing_room_names[:10])}"
        )

    return "\n".join(sections)


# =============================================================================
# Mob Generation Agent
# =============================================================================

mob_agent: Agent[MobGenerationContext, GeneratedMob] = Agent(
    get_default_model(),
    result_type=GeneratedMob,
    deps_type=MobGenerationContext,
    system_prompt=MOB_SYSTEM_PROMPT,
)


@mob_agent.system_prompt
def mob_dynamic_prompt(ctx: RunContext[MobGenerationContext]) -> str:
    """Add dynamic context to mob generation prompt."""
    deps = ctx.deps

    sections = []

    # Zone and room context
    sections.append(f"Zone theme: {deps.zone_theme}")
    sections.append(f"Room: {deps.room_description[:200]}")

    # Level and difficulty
    sections.append(f"Target level: {deps.target_level}")

    # Disposition
    sections.append(f"Behavior: {deps.disposition_hint.value}")

    # Combat style
    if deps.combat_style_hint:
        sections.append(f"Combat style: {deps.combat_style_hint.value}")

    # Boss generation
    if deps.is_boss_request:
        sections.append("THIS IS A BOSS MOB - make it powerful and memorable!")
        if deps.boss_phase:
            sections.append(f"Boss phase: {deps.boss_phase}/3")

    # Faction context
    if deps.faction_hints:
        sections.append(f"Factions in area: {', '.join(deps.faction_hints)}")

    # Avoid duplicates
    if deps.existing_mob_types:
        sections.append(
            f"Avoid these types (already exist): {', '.join(deps.existing_mob_types[:5])}"
        )

    # Vocabulary
    if deps.vocabulary_hints:
        sections.append(f"Theme vocabulary: {', '.join(deps.vocabulary_hints[:10])}")

    return "\n".join(sections)


# =============================================================================
# Item Generation Agent
# =============================================================================

item_agent: Agent[ItemGenerationContext, GeneratedItem] = Agent(
    get_default_model(),
    result_type=GeneratedItem,
    deps_type=ItemGenerationContext,
    system_prompt=ITEM_SYSTEM_PROMPT,
)


@item_agent.system_prompt
def item_dynamic_prompt(ctx: RunContext[ItemGenerationContext]) -> str:
    """Add dynamic context to item generation prompt."""
    deps = ctx.deps

    sections = []

    # Zone theme
    sections.append(f"Zone theme: {deps.zone_theme}")

    # Level and rarity
    sections.append(f"Target level: {deps.target_level}")
    sections.append(f"Target rarity: {deps.target_rarity.value}")

    # Type hints
    if deps.item_type_hint:
        sections.append(f"Item type: {deps.item_type_hint.value}")
    if deps.slot_hint:
        sections.append(f"Equipment slot: {deps.slot_hint.value}")

    # Source context
    if deps.dropped_by:
        sections.append(f"Dropped by: {deps.dropped_by}")

    # Boss loot
    if deps.is_boss_loot:
        sections.append("THIS IS BOSS LOOT - make it special and powerful!")

    # Avoid duplicates
    if deps.existing_item_names:
        sections.append(
            f"Avoid these names: {', '.join(deps.existing_item_names[:5])}"
        )

    # Vocabulary
    if deps.vocabulary_hints:
        sections.append(f"Theme vocabulary: {', '.join(deps.vocabulary_hints[:10])}")

    return "\n".join(sections)


# =============================================================================
# Combat Narration Agent (uses faster model)
# =============================================================================

combat_agent: Agent[CombatNarrationContext, CombatNarration] = Agent(
    get_fast_model(),
    result_type=CombatNarration,
    deps_type=CombatNarrationContext,
    system_prompt=COMBAT_SYSTEM_PROMPT,
)


@combat_agent.system_prompt
def combat_dynamic_prompt(ctx: RunContext[CombatNarrationContext]) -> str:
    """Add dynamic context to combat narration prompt."""
    deps = ctx.deps

    sections = []

    # Combatants
    sections.append(f"Attacker: {deps.attacker_name} ({deps.attacker_race})")
    if deps.attacker_class:
        sections.append(f"  Class: {deps.attacker_class}")
    if deps.attacker_weapon:
        sections.append(f"  Weapon: {deps.attacker_weapon}")

    sections.append(f"Defender: {deps.defender_name} ({deps.defender_race})")
    if deps.defender_armor:
        sections.append(f"  Armor: {deps.defender_armor}")

    # Combat result
    if deps.is_miss:
        sections.append("RESULT: MISS")
    elif deps.is_critical:
        sections.append(f"RESULT: CRITICAL HIT! {deps.damage_amount} {deps.damage_type.value} damage!")
    elif deps.is_killing_blow:
        sections.append(f"RESULT: KILLING BLOW! {deps.damage_amount} {deps.damage_type.value} damage!")
    else:
        sections.append(f"RESULT: HIT for {deps.damage_amount} {deps.damage_type.value} damage")

    # Skill used
    if deps.skill_used:
        sections.append(f"Skill/ability: {deps.skill_used}")

    # Health context
    sections.append(f"Attacker HP: {deps.attacker_health_percent}%")
    sections.append(f"Defender HP: {deps.defender_health_percent}%")

    # Round
    sections.append(f"Combat round: {deps.combat_round}")

    # Environment
    if deps.environment_hint:
        sections.append(f"Environment: {deps.environment_hint}")

    return "\n".join(sections)


# =============================================================================
# Dialogue Agent
# =============================================================================

dialogue_agent: Agent[DialogueContext, DialogueResponse] = Agent(
    get_default_model(),
    result_type=DialogueResponse,
    deps_type=DialogueContext,
    system_prompt=DIALOGUE_SYSTEM_PROMPT,
)


@dialogue_agent.system_prompt
def dialogue_dynamic_prompt(ctx: RunContext[DialogueContext]) -> str:
    """Add dynamic context to dialogue generation prompt."""
    deps = ctx.deps
    personality = deps.npc_personality

    sections = []

    # NPC identity
    sections.append(f"You are: {personality.name}")
    sections.append(f"Role: {personality.role}")
    sections.append(f"Speech style: {personality.speech_style.value}")
    sections.append(f"Current mood: {deps.current_mood.value}")

    # Background
    if personality.background:
        sections.append(f"Background: {personality.background}")
    if personality.motivation:
        sections.append(f"Motivation: {personality.motivation}")

    # Quirks and catchphrases
    if personality.quirks:
        sections.append(f"Quirks: {', '.join(personality.quirks)}")
    if personality.catchphrases:
        sections.append(f"Catchphrases: {', '.join(personality.catchphrases)}")

    # Player context
    sections.append(f"\nPlayer: {deps.player_name} ({deps.player_race})")
    if deps.player_class:
        sections.append(f"  Class: {deps.player_class}")
    sections.append(f"  Reputation: {deps.player_reputation}")
    sections.append(f"  First meeting: {deps.is_first_meeting}")

    # What player said
    sections.append(f"\nPlayer says: \"{deps.player_message}\"")

    # Topic
    if deps.topic:
        sections.append(f"Topic: {deps.topic}")

    # Knowledge topics
    if personality.knowledge_topics:
        sections.append(f"Topics NPC knows: {', '.join(personality.knowledge_topics)}")

    # Available quests/topics
    if deps.available_quests:
        sections.append(f"Quests NPC can offer: {', '.join(deps.available_quests)}")

    # Conversation history
    if deps.conversation_history:
        sections.append("\nRecent dialogue:")
        for line in deps.conversation_history[-5:]:
            sections.append(f"  {line}")

    # Context
    sections.append(f"\nTime: {deps.time_of_day}")
    sections.append(f"Location: {deps.location_name}")

    return "\n".join(sections)


# =============================================================================
# Quest Generation Agent
# =============================================================================

quest_agent: Agent[QuestGenerationContext, GeneratedQuest] = Agent(
    get_default_model(),
    result_type=GeneratedQuest,
    deps_type=QuestGenerationContext,
    system_prompt=QUEST_SYSTEM_PROMPT,
)


@quest_agent.system_prompt
def quest_dynamic_prompt(ctx: RunContext[QuestGenerationContext]) -> str:
    """Add dynamic context to quest generation prompt."""
    deps = ctx.deps

    sections = []

    # Zone theme and preferred archetypes
    theme = deps.zone_theme
    sections.append(f"Zone: {deps.target_zone_name} ({theme.zone_type.value})")
    if deps.target_zone_description:
        sections.append(f"Zone Theme: {deps.target_zone_description[:200]}")

    # Preferred quest types
    if theme.preferred_archetypes:
        preferred = ", ".join(a.value for a in theme.preferred_archetypes)
        sections.append(f"Preferred quest types for this zone: {preferred}")

    # Flavor vocabulary
    if theme.flavor_vocabulary:
        sections.append(f"Zone vocabulary: {', '.join(theme.flavor_vocabulary[:8])}")

    # Quest giver personality
    sections.append(f"\nQuest Giver: {deps.giver_name} ({deps.giver_role})")
    if deps.giver_personality:
        sections.append(f"Personality: {deps.giver_personality}")
    if deps.giver_faction:
        sections.append(f"Faction: {deps.giver_faction}")

    # Player context (CRITICAL for level scaling)
    sections.append(
        f"\nPlayer: Level {deps.player_level} {deps.player_race} {deps.player_class}"
    )
    sections.append(f"Active quests: {deps.player_active_quest_count}")
    sections.append(f"Completed quests: {deps.completed_quest_count}")

    # Variety control - avoid recently used archetypes
    if deps.recent_quest_types:
        avoid = ", ".join(t.value for t in deps.recent_quest_types[-3:])
        sections.append(f"\nAVOID these archetypes (recently used): {avoid}")

    # Available targets for grounding
    if deps.available_mob_types:
        sections.append(
            f"\nAvailable mob types (level-appropriate): {', '.join(deps.available_mob_types[:10])}"
        )
    if deps.available_locations:
        sections.append(
            f"Available locations: {', '.join(deps.available_locations[:10])}"
        )
    if deps.available_item_types:
        sections.append(
            f"Available item types: {', '.join(deps.available_item_types[:8])}"
        )
    if deps.available_npcs:
        sections.append(f"Available NPCs: {', '.join(deps.available_npcs[:8])}")

    # Difficulty scaling
    sections.append(f"\nTarget difficulty: {deps.target_difficulty}")
    if deps.xp_multiplier != 1.0:
        sections.append(f"XP Multiplier: {deps.xp_multiplier}x")

    # Quality reminders
    if deps.avoid_simple_grinds:
        sections.append(
            "\nREMINDER: Create an INTERESTING quest, not a boring grind!"
        )
    if deps.prefer_narrative:
        sections.append("Focus on STORY and CHARACTER, not just mechanics.")

    return "\n".join(sections)


# =============================================================================
# Crafting Agent
# =============================================================================

crafting_agent: Agent[CraftingContext, GeneratedCraftedItem] = Agent(
    get_default_model(),
    result_type=GeneratedCraftedItem,
    deps_type=CraftingContext,
    system_prompt=CRAFTING_SYSTEM_PROMPT,
)


@crafting_agent.system_prompt
def crafting_dynamic_prompt(ctx: RunContext[CraftingContext]) -> str:
    """Add dynamic context to crafting generation prompt."""
    deps = ctx.deps

    sections = []

    # Components being combined
    sections.append("COMPONENTS USED:")
    for comp in deps.components_used:
        quality_str = f"[{comp.quality.value}]" if comp.quality else ""
        rarity_str = f"({comp.rarity.value})" if comp.rarity else ""
        origin_str = f" from {comp.origin_zone}" if comp.origin_zone else ""
        sections.append(
            f"  - {comp.component_subtype} {comp.component_type} {quality_str} {rarity_str}{origin_str}"
        )

    # Summary if provided
    if deps.component_summary:
        sections.append(f"\nSummary: {deps.component_summary}")

    # Quality modifier
    quality_desc = {
        (0.5, 0.85): "poor overall quality",
        (0.85, 1.05): "average quality",
        (1.05, 1.2): "good quality",
        (1.2, 1.35): "excellent quality",
        (1.35, 1.5): "masterwork quality",
    }
    mod = deps.total_quality_modifier
    quality_text = "unknown quality"
    for (low, high), text in quality_desc.items():
        if low <= mod < high:
            quality_text = text
            break
    sections.append(f"\nCrafting quality: {quality_text} ({mod:.2f}x modifier)")
    sections.append(f"Average component quality: {deps.average_quality.value}")

    # Target output
    sections.append(f"\nTARGET OUTPUT:")
    sections.append(f"  Type: {deps.target_item_type.value}")
    sections.append(f"  Rarity: {deps.target_rarity.value}")
    sections.append(f"  Level: {deps.target_level}")
    if deps.target_slot:
        sections.append(f"  Slot: {deps.target_slot.value}")

    # Flavor context
    if deps.zone_theme:
        sections.append(f"\nZone theme influence: {deps.zone_theme}")
    if deps.player_class:
        sections.append(f"Crafter's class: {deps.player_class} (may influence style)")

    # Recipe context
    if deps.recipe_name:
        sections.append(f"\nFollowing recipe: {deps.recipe_name}")

    # Avoid duplicates
    if deps.existing_item_names:
        sections.append(
            f"\nAvoid these names (already exist): {', '.join(deps.existing_item_names[:5])}"
        )

    return "\n".join(sections)


# =============================================================================
# Agent Registry
# =============================================================================

AGENTS = {
    "room": room_agent,
    "mob": mob_agent,
    "item": item_agent,
    "combat": combat_agent,
    "dialogue": dialogue_agent,
    "quest": quest_agent,
    "crafting": crafting_agent,
}


def get_agent(name: str) -> Optional[Agent]:
    """Get an agent by name."""
    return AGENTS.get(name)


__all__ = [
    "room_agent",
    "mob_agent",
    "item_agent",
    "combat_agent",
    "dialogue_agent",
    "quest_agent",
    "crafting_agent",
    "get_agent",
    "AGENTS",
]
