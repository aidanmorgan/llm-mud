"""
Social Commands

Commands for interacting with NPCs - talk, ask, etc.
Uses the personality engine and LLM generation for dynamic dialogue.
"""

from typing import List, Optional

from core import EntityId
from core.component import get_component_actor
from .registry import command, CommandCategory
from ..components.position import Position


@command(
    name="talk",
    aliases=["speak", "greet"],
    category=CommandCategory.SOCIAL,
    help_text="Talk to an NPC in the room.",
    usage="talk <npc>",
    min_position=Position.STANDING,
)
async def cmd_talk(player_id: EntityId, args: List[str]) -> str:
    """Initiate conversation with an NPC."""
    if not args:
        return "Talk to whom?"

    target_keywords = " ".join(args).lower()

    # Find the target mob in the room
    mob_id, mob_identity = await _find_mob_in_room(player_id, target_keywords)
    if not mob_id:
        return f"You don't see '{target_keywords}' here."

    # Check if mob can be talked to
    ai_actor = get_component_actor("AI")
    ai_data = await ai_actor.get.remote(mob_id)

    if ai_data and ai_data.get("behavior_type") == "hostile":
        if ai_data.get("aggro_target"):
            return f"{mob_identity.get('name', 'It')} is too busy fighting to talk!"

    # Check for dynamic AI (personality-driven dialogue)
    dynamic_ai_actor = get_component_actor("DynamicAI")
    dynamic_ai = await dynamic_ai_actor.get.remote(mob_id)

    if dynamic_ai:
        # Use LLM-generated dialogue
        dialogue = await _generate_dialogue(mob_id, mob_identity, dynamic_ai)
        if dialogue:
            return _format_dialogue(mob_identity.get("name", "The creature"), dialogue)

    # Fallback to static dialogue if available
    dialogue_actor = get_component_actor("Dialogue")
    static_dialogue = await dialogue_actor.get.remote(mob_id)

    if static_dialogue:
        greetings = static_dialogue.get("greetings", [])
        if greetings:
            import random

            greeting = random.choice(greetings)
            name = mob_identity.get("name", "The creature")
            return f'{name} says, "{greeting}"'

    # No dialogue available
    name = mob_identity.get("name", "The creature")
    return f"{name} doesn't seem interested in talking."


@command(
    name="ask",
    category=CommandCategory.SOCIAL,
    help_text="Ask an NPC about a specific topic.",
    usage="ask <npc> about <topic>",
    min_position=Position.STANDING,
)
async def cmd_ask(player_id: EntityId, args: List[str]) -> str:
    """Ask an NPC about a topic."""
    if not args:
        return "Ask who about what?"

    # Parse "ask <target> about <topic>"
    args_str = " ".join(args)
    if " about " not in args_str.lower():
        return "Usage: ask <npc> about <topic>"

    parts = args_str.lower().split(" about ", 1)
    target_keywords = parts[0].strip()
    topic = parts[1].strip() if len(parts) > 1 else ""

    if not topic:
        return "Ask about what?"

    # Find the target mob
    mob_id, mob_identity = await _find_mob_in_room(player_id, target_keywords)
    if not mob_id:
        return f"You don't see '{target_keywords}' here."

    name = mob_identity.get("name", "The creature")

    # Check for dynamic AI
    dynamic_ai_actor = get_component_actor("DynamicAI")
    dynamic_ai = await dynamic_ai_actor.get.remote(mob_id)

    if dynamic_ai:
        # Generate a topic-specific response
        response = await _generate_topic_response(mob_id, mob_identity, dynamic_ai, topic)
        if response:
            return f'You ask {name} about {topic}.\n\n{name} says, "{response}"'

    # Check static dialogue topics
    dialogue_actor = get_component_actor("Dialogue")
    static_dialogue = await dialogue_actor.get.remote(mob_id)

    if static_dialogue:
        topics = static_dialogue.get("topics", {})
        # Try exact match first
        if topic in topics:
            return f'You ask {name} about {topic}.\n\n{name} says, "{topics[topic]}"'
        # Try partial match
        for key, response in topics.items():
            if topic in key or key in topic:
                return f'You ask {name} about {topic}.\n\n{name} says, "{response}"'

    return f"{name} doesn't know anything about that."


# =============================================================================
# Helper Functions
# =============================================================================


async def _find_mob_in_room(
    player_id: EntityId, keywords: str
) -> tuple[Optional[EntityId], dict]:
    """Find a mob in the player's room by keywords."""
    location_actor = get_component_actor("Location")
    identity_actor = get_component_actor("Identity")

    # Get player's location
    player_location = await location_actor.get.remote(player_id)
    if not player_location:
        return None, {}

    room_id = player_location.get("room_id")
    if not room_id:
        return None, {}

    # Find all entities in the room
    all_locations = await location_actor.get_all.remote()

    for entity_id, location in all_locations.items():
        if location.get("room_id") != room_id:
            continue
        if entity_id.entity_type not in ("mob", "npc"):
            continue

        # Check if keywords match
        identity = await identity_actor.get.remote(entity_id)
        if not identity:
            continue

        mob_keywords = identity.get("keywords", [])
        mob_name = identity.get("name", "").lower()

        # Match by keyword list
        for kw in mob_keywords:
            if keywords in kw.lower() or kw.lower() in keywords:
                return entity_id, identity

        # Match by name
        if keywords in mob_name:
            return entity_id, identity

    return None, {}


async def _generate_dialogue(
    mob_id: EntityId, identity: dict, dynamic_ai: dict
) -> Optional[dict]:
    """Generate dialogue for a mob using the LLM."""
    from generation.engine import get_generation_engine, generation_engine_exists
    from generation.personality import PersonalityEngine
    from llm.prompts import DialogueContext
    from llm.schemas import MobPersonality, CombatStyle, PersonalityTrait

    if not generation_engine_exists():
        return None

    engine = get_generation_engine()

    # Build personality from dynamic AI data
    personality_data = dynamic_ai.get("personality", {})
    try:
        personality = MobPersonality(
            traits=[PersonalityTrait(t) for t in personality_data.get("traits", ["hostile"])],
            combat_style=CombatStyle(personality_data.get("combat_style", "tactical")),
            flee_threshold=personality_data.get("flee_threshold", 0.2),
            dialogue_style=personality_data.get("dialogue_style", "speaks tersely"),
            motivations=personality_data.get("motivations", []),
            fears=personality_data.get("fears", []),
        )
    except (ValueError, KeyError):
        return None

    # Get dialogue style from personality engine
    engine_instance = PersonalityEngine(personality)
    dialogue_style = engine_instance.get_dialogue_style_prompt()

    # Build dialogue context
    context = DialogueContext(
        mob_name=identity.get("name", "creature"),
        mob_description=identity.get("long_description", ""),
        personality_traits=[t.value for t in personality.traits],
        dialogue_style=dialogue_style,
        role=dynamic_ai.get("role", ""),
        knowledge_topics=dynamic_ai.get("knowledge_topics", []),
    )

    # Get theme from instance or use default
    theme_id = dynamic_ai.get("theme_id", "dark_cave")

    try:
        result = await engine.generate_dialogue.remote(theme_id, context)
        if result:
            return {
                "greeting": result.greeting,
                "farewell": result.farewell,
                "topics": {t.keyword: t.response for t in result.topics},
                "combat_taunt": result.combat_taunt,
            }
    except Exception:
        pass

    return None


async def _generate_topic_response(
    mob_id: EntityId, identity: dict, dynamic_ai: dict, topic: str
) -> Optional[str]:
    """Generate a response to a specific topic using the LLM."""
    from generation.engine import get_generation_engine, generation_engine_exists
    from llm.prompts import DialogueContext

    if not generation_engine_exists():
        return None

    engine = get_generation_engine()

    personality_data = dynamic_ai.get("personality", {})
    dialogue_style = personality_data.get("dialogue_style", "speaks tersely")
    traits = personality_data.get("traits", ["hostile"])

    # Build a dialogue context focused on the topic
    context = DialogueContext(
        mob_name=identity.get("name", "creature"),
        mob_description=identity.get("long_description", ""),
        personality_traits=traits,
        dialogue_style=dialogue_style,
        role=dynamic_ai.get("role", ""),
        knowledge_topics=[topic],  # Focus on the specific topic
    )

    theme_id = dynamic_ai.get("theme_id", "dark_cave")

    try:
        result = await engine.generate_dialogue.remote(theme_id, context)
        if result and result.topics:
            # Return the first topic response (should be about the asked topic)
            return result.topics[0].response
    except Exception:
        pass

    return None


def _format_dialogue(name: str, dialogue: dict) -> str:
    """Format dialogue for display."""
    lines = [f'{name} turns to you and says, "{dialogue.get("greeting", "Hello.")}"']

    topics = dialogue.get("topics", {})
    if topics:
        topic_list = ", ".join(topics.keys())
        lines.append(f"\n[You can ASK {name.upper()} ABOUT: {topic_list}]")

    return "\n".join(lines)
