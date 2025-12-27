"""
Character Creation Commands

Commands and handlers for the character creation flow.
Players progress through states: name -> race -> class -> stats -> confirm.
"""

import logging
import re
from typing import List, Optional, Dict, Any

from core import EntityId
from .registry import command, CommandCategory
from ..components.position import Position
from ..components.character import (
    CreationState,
    CharacterCreationData,
    ClassData,
    RaceData,
    StatModifiers,
)


logger = logging.getLogger(__name__)


# Valid name pattern: 3-15 characters, letters only, starts with uppercase
NAME_PATTERN = re.compile(r"^[A-Z][a-z]{2,14}$")


def _format_stat_bar(value: int, base: int = 10) -> str:
    """Format a stat value with visual indicator of bonus/penalty."""
    diff = value - base
    if diff > 0:
        return f"{value} (+{diff})"
    elif diff < 0:
        return f"{value} ({diff})"
    return str(value)


async def _get_creation_data(player_id: EntityId) -> Optional[CharacterCreationData]:
    """Get character creation data for a player."""
    from core.component import get_component_actor

    creation_actor = get_component_actor("CharacterCreation")
    return await creation_actor.get.remote(player_id)


async def _save_creation_data(player_id: EntityId, data: CharacterCreationData) -> None:
    """Save character creation data."""
    from core.component import get_component_actor

    creation_actor = get_component_actor("CharacterCreation")
    await creation_actor.set.remote(player_id, data)


async def _get_class_templates() -> List[Any]:
    """Get all available class templates."""
    from ..world.character_registry import get_character_registry

    registry = get_character_registry()
    return registry.get_all_classes()


async def _get_race_templates() -> List[Any]:
    """Get all available race templates."""
    from ..world.character_registry import get_character_registry

    registry = get_character_registry()
    return registry.get_all_races()


async def _get_class_template(class_id: str) -> Optional[Any]:
    """Get a specific class template."""
    from ..world.character_registry import get_character_registry

    registry = get_character_registry()
    return registry.get_class(class_id)


async def _get_race_template(race_id: str) -> Optional[Any]:
    """Get a specific race template."""
    from ..world.character_registry import get_character_registry

    registry = get_character_registry()
    return registry.get_race(race_id)


def _format_welcome_screen() -> str:
    """Format the welcome screen for character creation."""
    return """
================================================================================
                     WELCOME TO THE REALM
================================================================================

You stand at the threshold of a new adventure. Before you can enter
the world, you must first create your character.

Your choices here will shape your destiny:
  - Your NAME will be how others know you
  - Your RACE determines your natural abilities and traits
  - Your CLASS defines your skills and combat style
  - Your ATTRIBUTES determine your strengths and weaknesses

Type 'begin' to start creating your character.
Type 'quit' to leave.

================================================================================
"""


def _format_name_prompt() -> str:
    """Format the name selection prompt."""
    return """
================================================================================
                        CHOOSE YOUR NAME
================================================================================

Your name is how you will be known throughout the realm.

Requirements:
  - Must be 3-15 characters long
  - Must contain only letters
  - Must start with a capital letter (e.g., Aragorn, Gandalf, Elara)

Enter your desired name:
"""


async def _format_race_selection() -> str:
    """Format the race selection screen."""
    races = await _get_race_templates()

    lines = [
        "",
        "=" * 80,
        "                         CHOOSE YOUR RACE",
        "=" * 80,
        "",
        "Your race determines your natural abilities, resistances, and starting traits.",
        "",
    ]

    for race in races:
        # Format stat modifiers
        mods = []
        for stat, val in race.stat_modifiers.items():
            if val > 0:
                mods.append(f"+{val} {stat[:3].upper()}")
            elif val < 0:
                mods.append(f"{val} {stat[:3].upper()}")

        mod_str = ", ".join(mods) if mods else "No stat modifiers"

        # Format abilities
        abilities = ", ".join(race.racial_abilities) if race.racial_abilities else "None"

        lines.extend([
            f"  {race.race_id.upper():12s} - {race.name}",
            f"                 Stats: {mod_str}",
            f"                 Abilities: {abilities}",
            "",
        ])

    lines.extend([
        "-" * 80,
        "Type the name of a race to see more details, or type it to select.",
        "Type 'back' to return to the previous step.",
        "",
    ])

    return "\n".join(lines)


async def _format_race_details(race_id: str) -> str:
    """Format detailed race information."""
    race = await _get_race_template(race_id)
    if not race:
        return f"Unknown race: {race_id}"

    lines = [
        "",
        "=" * 80,
        f"                         {race.name.upper()}",
        "=" * 80,
        "",
        race.description,
        "",
        "Stat Modifiers:",
    ]

    for stat in ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]:
        val = race.stat_modifiers.get(stat, 0)
        if val != 0:
            sign = "+" if val > 0 else ""
            lines.append(f"  {stat.capitalize():15s} {sign}{val}")

    if race.racial_abilities:
        lines.append("")
        lines.append("Racial Abilities:")
        for ability in race.racial_abilities:
            lines.append(f"  - {ability.replace('_', ' ').title()}")

    if race.resistances:
        lines.append("")
        lines.append("Resistances:")
        for resist, value in race.resistances.items():
            lines.append(f"  - {resist.capitalize()}: {value}%")

    lines.extend([
        "",
        f"Size: {race.size.capitalize()}",
        f"Speed: {race.speed_modifier}%",
        f"Languages: {', '.join(race.languages)}",
        "",
        "-" * 80,
        f"Type '{race.race_id}' again to select this race, or choose another.",
        "",
    ])

    return "\n".join(lines)


async def _format_class_selection() -> str:
    """Format the class selection screen."""
    classes = await _get_class_templates()

    lines = [
        "",
        "=" * 80,
        "                         CHOOSE YOUR CLASS",
        "=" * 80,
        "",
        "Your class determines your combat style, skills, and equipment proficiencies.",
        "",
    ]

    for cls in classes:
        # Format stat modifiers
        mods = []
        for stat, val in cls.stat_modifiers.items():
            if val > 0:
                mods.append(f"+{val} {stat[:3].upper()}")
            elif val < 0:
                mods.append(f"{val} {stat[:3].upper()}")

        mod_str = ", ".join(mods) if mods else "No stat modifiers"

        # Key stats
        hp_mp = f"HP/lvl: {cls.health_per_level}, MP/lvl: {cls.mana_per_level}"

        lines.extend([
            f"  {cls.class_id.upper():12s} - {cls.name}",
            f"                 Stats: {mod_str}",
            f"                 {hp_mp}",
            "",
        ])

    lines.extend([
        "-" * 80,
        "Type the name of a class to see more details, or type it to select.",
        "Type 'back' to return to the previous step.",
        "",
    ])

    return "\n".join(lines)


async def _format_class_details(class_id: str) -> str:
    """Format detailed class information."""
    cls = await _get_class_template(class_id)
    if not cls:
        return f"Unknown class: {class_id}"

    lines = [
        "",
        "=" * 80,
        f"                         {cls.name.upper()}",
        "=" * 80,
        "",
        cls.description,
        "",
        "Stat Modifiers:",
    ]

    for stat in ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]:
        val = cls.stat_modifiers.get(stat, 0)
        if val != 0:
            sign = "+" if val > 0 else ""
            lines.append(f"  {stat.capitalize():15s} {sign}{val}")

    lines.append("")
    lines.append("Growth per Level:")
    lines.append(f"  Health: +{cls.health_per_level}")
    lines.append(f"  Mana:   +{cls.mana_per_level}")

    lines.append("")
    lines.append(f"Starting Health: {cls.starting_health}")
    lines.append(f"Starting Mana:   {cls.starting_mana}")
    lines.append(f"Starting Gold:   {cls.starting_gold}")

    lines.append("")
    lines.append(f"Prime Attribute: {cls.prime_attribute.capitalize()}")

    if cls.starting_skills:
        lines.append("")
        lines.append("Starting Skills:")
        for skill in cls.starting_skills:
            lines.append(f"  - {skill.replace('_', ' ').title()}")

    if cls.class_skills:
        lines.append("")
        lines.append("Class Skills (learned through training):")
        for skill in cls.class_skills[:5]:  # Show first 5
            lines.append(f"  - {skill.replace('_', ' ').title()}")
        if len(cls.class_skills) > 5:
            lines.append(f"  ... and {len(cls.class_skills) - 5} more")

    if cls.armor_proficiency:
        lines.append("")
        lines.append(f"Armor: {', '.join(cls.armor_proficiency)}")

    if cls.weapon_proficiency:
        lines.append(f"Weapons: {', '.join(cls.weapon_proficiency)}")

    lines.extend([
        "",
        "-" * 80,
        f"Type '{cls.class_id}' again to select this class, or choose another.",
        "",
    ])

    return "\n".join(lines)


def _format_stat_allocation(creation: CharacterCreationData) -> str:
    """Format the stat allocation screen."""
    lines = [
        "",
        "=" * 80,
        "                      ALLOCATE YOUR ATTRIBUTES",
        "=" * 80,
        "",
        "Distribute your attribute points to customize your character.",
        f"Points remaining: {creation.points_remaining}",
        "",
        "Current Attributes (base 10, min 8, max 18):",
        "",
    ]

    stat_names = {
        "strength": "STR - Physical power, melee damage",
        "dexterity": "DEX - Agility, accuracy, defense",
        "constitution": "CON - Health, stamina, resistance",
        "intelligence": "INT - Spell power, mana pool",
        "wisdom": "WIS - Perception, mana regen",
        "charisma": "CHA - Social skills, prices",
    }

    for stat, desc in stat_names.items():
        value = creation.allocated_stats.get(stat, 10)
        bar = "#" * (value - 7)  # Visual bar
        lines.append(f"  {stat[:3].upper()}: {value:2d}  [{bar:11s}]  {desc}")

    lines.extend([
        "",
        "-" * 80,
        "Commands:",
        "  add <stat>      - Add 1 point to a stat (e.g., 'add str')",
        "  remove <stat>   - Remove 1 point from a stat",
        "  reset           - Reset all stats to base 10",
        "  done            - Finish allocation and continue",
        "  back            - Return to class selection",
        "",
    ])

    return "\n".join(lines)


async def _format_confirmation(creation: CharacterCreationData) -> str:
    """Format the confirmation screen."""
    race = await _get_race_template(creation.chosen_race) if creation.chosen_race else None
    cls = await _get_class_template(creation.chosen_class) if creation.chosen_class else None

    lines = [
        "",
        "=" * 80,
        "                      CONFIRM YOUR CHARACTER",
        "=" * 80,
        "",
        f"  Name:  {creation.chosen_name}",
        f"  Race:  {race.name if race else 'Unknown'}",
        f"  Class: {cls.name if cls else 'Unknown'}",
        "",
        "  Final Attributes (including race and class bonuses):",
    ]

    # Calculate final stats with modifiers
    for stat in ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]:
        base = creation.allocated_stats.get(stat, 10)
        race_mod = race.stat_modifiers.get(stat, 0) if race else 0
        class_mod = cls.stat_modifiers.get(stat, 0) if cls else 0
        final = base + race_mod + class_mod

        mod_parts = []
        if race_mod != 0:
            mod_parts.append(f"race {'+' if race_mod > 0 else ''}{race_mod}")
        if class_mod != 0:
            mod_parts.append(f"class {'+' if class_mod > 0 else ''}{class_mod}")

        mod_str = f" ({', '.join(mod_parts)})" if mod_parts else ""
        lines.append(f"    {stat.capitalize():15s} {final:2d}{mod_str}")

    if cls:
        lines.extend([
            "",
            f"  Starting Health: {cls.starting_health}",
            f"  Starting Mana:   {cls.starting_mana}",
            f"  Starting Gold:   {cls.starting_gold}",
        ])

    if race and race.racial_abilities:
        lines.append("")
        lines.append("  Racial Abilities:")
        for ability in race.racial_abilities:
            lines.append(f"    - {ability.replace('_', ' ').title()}")

    if cls and cls.starting_skills:
        lines.append("")
        lines.append("  Starting Skills:")
        for skill in cls.starting_skills:
            lines.append(f"    - {skill.replace('_', ' ').title()}")

    lines.extend([
        "",
        "=" * 80,
        "",
        "Type 'confirm' to create this character and enter the world.",
        "Type 'back' to make changes to your attributes.",
        "Type 'restart' to start over from the beginning.",
        "",
    ])

    return "\n".join(lines)


async def handle_creation_input(
    player_id: EntityId, creation: CharacterCreationData, input_text: str
) -> str:
    """
    Handle input during character creation based on current state.

    Returns the response to send to the player.
    """
    input_lower = input_text.lower().strip()

    # Handle universal commands
    if input_lower == "quit":
        return "Character creation cancelled. Goodbye!"

    # State-specific handling
    if creation.state == CreationState.WELCOME:
        return await _handle_welcome(player_id, creation, input_lower)
    elif creation.state == CreationState.CHOOSE_NAME:
        return await _handle_name_input(player_id, creation, input_text)
    elif creation.state == CreationState.CHOOSE_RACE:
        return await _handle_race_input(player_id, creation, input_lower)
    elif creation.state == CreationState.CHOOSE_CLASS:
        return await _handle_class_input(player_id, creation, input_lower)
    elif creation.state == CreationState.ALLOCATE_STATS:
        return await _handle_stat_input(player_id, creation, input_lower)
    elif creation.state == CreationState.CONFIRM:
        return await _handle_confirm_input(player_id, creation, input_lower)
    else:
        return "Character creation complete."


async def _handle_welcome(
    player_id: EntityId, creation: CharacterCreationData, input_text: str
) -> str:
    """Handle input at the welcome screen."""
    if input_text in ("begin", "start", "yes", "y"):
        creation.state = CreationState.CHOOSE_NAME
        await _save_creation_data(player_id, creation)
        return _format_name_prompt()

    return _format_welcome_screen()


async def _handle_name_input(
    player_id: EntityId, creation: CharacterCreationData, input_text: str
) -> str:
    """Handle name input."""
    if input_text.lower() == "back":
        creation.state = CreationState.WELCOME
        await _save_creation_data(player_id, creation)
        return _format_welcome_screen()

    # Capitalize first letter, lowercase rest
    name = input_text.strip().capitalize()

    # Validate name
    if not NAME_PATTERN.match(name):
        creation.name_attempts += 1
        if creation.name_attempts >= creation.max_name_attempts:
            return (
                "Too many invalid attempts. Please try simpler names like:\n"
                "  Conan, Elara, Gandalf, Luna, Marcus\n\n"
                "Enter your desired name:"
            )
        return (
            f"'{input_text}' is not a valid name.\n\n"
            "Requirements:\n"
            "  - 3-15 letters only\n"
            "  - Must start with a capital letter\n\n"
            "Enter your desired name:"
        )

    # Check if name is taken (would need to query player database)
    # For now, we'll skip this check

    creation.chosen_name = name
    creation.state = CreationState.CHOOSE_RACE
    await _save_creation_data(player_id, creation)

    return f"Your name shall be {name}.\n" + await _format_race_selection()


async def _handle_race_input(
    player_id: EntityId, creation: CharacterCreationData, input_text: str
) -> str:
    """Handle race selection input."""
    if input_text == "back":
        creation.state = CreationState.CHOOSE_NAME
        await _save_creation_data(player_id, creation)
        return _format_name_prompt()

    # Check if it's a valid race
    races = await _get_race_templates()
    race_ids = [r.race_id for r in races]

    if input_text in race_ids:
        # If they already viewed details, select it
        if creation.chosen_race == input_text:
            creation.state = CreationState.CHOOSE_CLASS
            await _save_creation_data(player_id, creation)
            race = await _get_race_template(input_text)
            return f"You have chosen to be {race.name if race else input_text}.\n" + await _format_class_selection()

        # First time - show details
        creation.chosen_race = input_text
        await _save_creation_data(player_id, creation)
        return await _format_race_details(input_text)

    # Try partial match
    for race_id in race_ids:
        if race_id.startswith(input_text) or input_text in race_id:
            if creation.chosen_race == race_id:
                creation.state = CreationState.CHOOSE_CLASS
                await _save_creation_data(player_id, creation)
                race = await _get_race_template(race_id)
                return f"You have chosen to be {race.name if race else race_id}.\n" + await _format_class_selection()

            creation.chosen_race = race_id
            await _save_creation_data(player_id, creation)
            return await _format_race_details(race_id)

    return f"Unknown race: '{input_text}'. Please choose from the list.\n" + await _format_race_selection()


async def _handle_class_input(
    player_id: EntityId, creation: CharacterCreationData, input_text: str
) -> str:
    """Handle class selection input."""
    if input_text == "back":
        creation.state = CreationState.CHOOSE_RACE
        creation.chosen_race = None
        await _save_creation_data(player_id, creation)
        return await _format_race_selection()

    # Check if it's a valid class
    classes = await _get_class_templates()
    class_ids = [c.class_id for c in classes]

    if input_text in class_ids:
        # If they already viewed details, select it
        if creation.chosen_class == input_text:
            creation.state = CreationState.ALLOCATE_STATS
            await _save_creation_data(player_id, creation)
            cls = await _get_class_template(input_text)
            return f"You have chosen the path of the {cls.name if cls else input_text}.\n" + _format_stat_allocation(creation)

        # First time - show details
        creation.chosen_class = input_text
        await _save_creation_data(player_id, creation)
        return await _format_class_details(input_text)

    # Try partial match
    for class_id in class_ids:
        if class_id.startswith(input_text) or input_text in class_id:
            if creation.chosen_class == class_id:
                creation.state = CreationState.ALLOCATE_STATS
                await _save_creation_data(player_id, creation)
                cls = await _get_class_template(class_id)
                return f"You have chosen the path of the {cls.name if cls else class_id}.\n" + _format_stat_allocation(creation)

            creation.chosen_class = class_id
            await _save_creation_data(player_id, creation)
            return await _format_class_details(class_id)

    return f"Unknown class: '{input_text}'. Please choose from the list.\n" + await _format_class_selection()


async def _handle_stat_input(
    player_id: EntityId, creation: CharacterCreationData, input_text: str
) -> str:
    """Handle stat allocation input."""
    if input_text == "back":
        creation.state = CreationState.CHOOSE_CLASS
        creation.chosen_class = None
        await _save_creation_data(player_id, creation)
        return await _format_class_selection()

    if input_text == "done":
        creation.state = CreationState.CONFIRM
        await _save_creation_data(player_id, creation)
        return await _format_confirmation(creation)

    if input_text == "reset":
        creation.points_remaining = 15
        creation.allocated_stats = {
            "strength": 10,
            "dexterity": 10,
            "constitution": 10,
            "intelligence": 10,
            "wisdom": 10,
            "charisma": 10,
        }
        await _save_creation_data(player_id, creation)
        return "Stats reset to base values.\n" + _format_stat_allocation(creation)

    # Parse add/remove commands
    parts = input_text.split()
    if len(parts) >= 2:
        action = parts[0]
        stat_abbr = parts[1].lower()

        # Map abbreviations to full stat names
        stat_map = {
            "str": "strength",
            "strength": "strength",
            "dex": "dexterity",
            "dexterity": "dexterity",
            "con": "constitution",
            "constitution": "constitution",
            "int": "intelligence",
            "intelligence": "intelligence",
            "wis": "wisdom",
            "wisdom": "wisdom",
            "cha": "charisma",
            "charisma": "charisma",
        }

        stat = stat_map.get(stat_abbr)
        if not stat:
            return f"Unknown stat: {stat_abbr}. Use str, dex, con, int, wis, or cha.\n" + _format_stat_allocation(creation)

        if action == "add":
            if creation.can_allocate(stat):
                creation.allocate(stat)
                await _save_creation_data(player_id, creation)
                return _format_stat_allocation(creation)
            else:
                if creation.points_remaining <= 0:
                    return "You have no points remaining. Use 'done' to continue or 'remove' to free points.\n" + _format_stat_allocation(creation)
                return f"{stat.capitalize()} is already at maximum (18).\n" + _format_stat_allocation(creation)

        elif action in ("remove", "rem", "sub"):
            if creation.deallocate(stat):
                await _save_creation_data(player_id, creation)
                return _format_stat_allocation(creation)
            else:
                return f"{stat.capitalize()} is already at minimum (8).\n" + _format_stat_allocation(creation)

    return "Unknown command. Use 'add <stat>', 'remove <stat>', 'reset', or 'done'.\n" + _format_stat_allocation(creation)


async def _handle_confirm_input(
    player_id: EntityId, creation: CharacterCreationData, input_text: str
) -> str:
    """Handle confirmation input."""
    if input_text == "back":
        creation.state = CreationState.ALLOCATE_STATS
        await _save_creation_data(player_id, creation)
        return _format_stat_allocation(creation)

    if input_text == "restart":
        creation.reset()
        await _save_creation_data(player_id, creation)
        return _format_welcome_screen()

    if input_text in ("confirm", "yes", "y", "create"):
        # Finalize character creation
        creation.state = CreationState.COMPLETE
        await _save_creation_data(player_id, creation)

        # The actual player creation happens in the login/connection flow
        # Here we just mark creation as complete
        return await _finalize_character(player_id, creation)

    return "Type 'confirm' to create your character, 'back' to make changes, or 'restart' to begin again.\n" + await _format_confirmation(creation)


async def _finalize_character(player_id: EntityId, creation: CharacterCreationData) -> str:
    """
    Finalize character creation and apply all choices.

    Updates the player entity with race, class, stats, and starting equipment.
    """
    from core.component import get_component_actor
    from ..world.character_registry import get_character_registry

    registry = get_character_registry()
    race = registry.get_race(creation.chosen_race) if creation.chosen_race else None
    cls = registry.get_class(creation.chosen_class) if creation.chosen_class else None

    # Update player identity with chosen name
    identity_actor = get_component_actor("Identity")
    identity = await identity_actor.get.remote(player_id)
    if identity:
        identity.name = creation.chosen_name
        identity.keywords = [creation.chosen_name.lower()]
        identity.short_description = f"{creation.chosen_name} is here."
        await identity_actor.set.remote(player_id, identity)

    # Update player stats with final values
    stats_actor = get_component_actor("Stats")
    stats = await stats_actor.get.remote(player_id)
    if stats:
        # Apply base allocated stats
        for stat_name in ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]:
            base_val = creation.allocated_stats.get(stat_name, 10)
            race_mod = race.stat_modifiers.get(stat_name, 0) if race else 0
            class_mod = cls.stat_modifiers.get(stat_name, 0) if cls else 0
            final_val = base_val + race_mod + class_mod
            setattr(stats.attributes, stat_name, final_val)

        # Apply class values
        if cls:
            stats.class_name = cls.name
            stats.max_health = cls.starting_health
            stats.current_health = cls.starting_health
            stats.max_mana = cls.starting_mana
            stats.current_mana = cls.starting_mana
            stats.gold = cls.starting_gold

        # Apply race values
        if race:
            stats.race_name = race.name

        await stats_actor.set.remote(player_id, stats)

    # Create ClassData component
    if cls:
        class_actor = get_component_actor("Class")
        class_data = ClassData()
        class_data.class_id = cls.class_id
        class_data.class_name = cls.name
        class_data.class_skills = cls.class_skills.copy()
        class_data.health_per_level = cls.health_per_level
        class_data.mana_per_level = cls.mana_per_level
        class_data.prime_attribute = cls.prime_attribute
        await class_actor.create.remote(player_id, lambda c: _copy_class_data(c, class_data))

    # Create RaceData component
    if race:
        race_actor = get_component_actor("Race")
        race_data = RaceData()
        race_data.race_id = race.race_id
        race_data.race_name = race.name
        race_data.stat_modifiers = StatModifiers(**race.stat_modifiers)
        race_data.racial_abilities = race.racial_abilities.copy()
        race_data.infravision = race.infravision
        race_data.darkvision = race.darkvision
        race_data.resistances = race.resistances.copy()
        race_data.languages = race.languages.copy()
        await race_actor.create.remote(player_id, lambda c: _copy_race_data(c, race_data))

    # Create starting equipment
    if cls and cls.starting_equipment:
        from ..world.factory import get_entity_factory

        factory = get_entity_factory()
        container_actor = get_component_actor("Container")
        container = await container_actor.get.remote(player_id)

        if container:
            for item_id in cls.starting_equipment:
                item = await factory.create_item(item_id)
                if item:
                    container.contents.append(item)
            await container_actor.set.remote(player_id, container)

    # Move player to starting room
    starting_room = cls.starting_room if cls else "ravenmoor_square"
    if race and race.starting_room_override:
        starting_room = race.starting_room_override

    location_actor = get_component_actor("Location")
    location = await location_actor.get.remote(player_id)
    if location:
        # Resolve room ID from template ID
        from ..world.templates import get_template_registry

        registry = get_template_registry()
        room_template = registry.get_room(starting_room)
        if room_template:
            location.room_id = EntityId(id=starting_room, entity_type="room")
        await location_actor.set.remote(player_id, location)

    # Remove CharacterCreation component (no longer needed)
    creation_actor = get_component_actor("CharacterCreation")
    await creation_actor.remove.remote(player_id)

    # Return welcome message
    return f"""
================================================================================
                     CHARACTER CREATION COMPLETE
================================================================================

Welcome to the realm, {creation.chosen_name}!

You are a {race.name if race else 'Human'} {cls.name if cls else 'Adventurer'}.

You have entered the world in {starting_room.replace('_', ' ').title()}.

Type 'look' to see your surroundings.
Type 'help' for a list of commands.

May your adventures be legendary!

================================================================================
"""


def _copy_class_data(target: ClassData, source: ClassData) -> None:
    """Copy class data from source to target."""
    target.class_id = source.class_id
    target.class_name = source.class_name
    target.class_skills = source.class_skills.copy()
    target.health_per_level = source.health_per_level
    target.mana_per_level = source.mana_per_level
    target.prime_attribute = source.prime_attribute


def _copy_race_data(target: RaceData, source: RaceData) -> None:
    """Copy race data from source to target."""
    target.race_id = source.race_id
    target.race_name = source.race_name
    target.stat_modifiers = source.stat_modifiers
    target.racial_abilities = source.racial_abilities.copy()
    target.infravision = source.infravision
    target.darkvision = source.darkvision
    target.resistances = source.resistances.copy()
    target.languages = source.languages.copy()


@command(
    name="create",
    category=CommandCategory.INFORMATION,
    help_text="Start or continue character creation.",
    usage="create",
    min_position=Position.DEAD,
)
async def cmd_create(player_id: EntityId, args: List[str]) -> str:
    """Start or continue character creation process."""
    from core.component import get_component_actor

    # Check if player already has a CharacterCreation component
    creation = await _get_creation_data(player_id)

    if creation:
        # Continue from current state
        if creation.is_complete():
            return "Your character has already been created!"

        # Resume creation
        if creation.state == CreationState.WELCOME:
            return _format_welcome_screen()
        elif creation.state == CreationState.CHOOSE_NAME:
            return _format_name_prompt()
        elif creation.state == CreationState.CHOOSE_RACE:
            return await _format_race_selection()
        elif creation.state == CreationState.CHOOSE_CLASS:
            return await _format_class_selection()
        elif creation.state == CreationState.ALLOCATE_STATS:
            return _format_stat_allocation(creation)
        elif creation.state == CreationState.CONFIRM:
            return await _format_confirmation(creation)

    # Create new CharacterCreation component
    creation_actor = get_component_actor("CharacterCreation")
    await creation_actor.create.remote(player_id, lambda c: None)

    creation = CharacterCreationData()
    await _save_creation_data(player_id, creation)

    return _format_welcome_screen()


@command(
    name="races",
    category=CommandCategory.INFORMATION,
    help_text="View available character races.",
    usage="races [race_name]",
    min_position=Position.DEAD,
)
async def cmd_races(player_id: EntityId, args: List[str]) -> str:
    """View available races or details about a specific race."""
    if args:
        race_id = args[0].lower()
        race = await _get_race_template(race_id)
        if race:
            return await _format_race_details(race_id)
        return f"Unknown race: {race_id}. Type 'races' to see all available races."

    return await _format_race_selection()


@command(
    name="classes",
    category=CommandCategory.INFORMATION,
    help_text="View available character classes.",
    usage="classes [class_name]",
    min_position=Position.DEAD,
)
async def cmd_classes(player_id: EntityId, args: List[str]) -> str:
    """View available classes or details about a specific class."""
    if args:
        class_id = args[0].lower()
        cls = await _get_class_template(class_id)
        if cls:
            return await _format_class_details(class_id)
        return f"Unknown class: {class_id}. Type 'classes' to see all available classes."

    return await _format_class_selection()
