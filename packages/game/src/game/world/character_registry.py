"""
Character Definition Registry

Loads and provides access to class and race definitions from YAML files.
"""

import logging
from dataclasses import fields
from pathlib import Path
from typing import Dict, List, Optional, Any

import yaml

from ..components.character import (
    ClassTemplate,
    RaceTemplate,
    StatModifiers,
)


logger = logging.getLogger(__name__)


class CharacterDefinitionRegistry:
    """
    Registry for character class and race definitions.

    Loads definitions from YAML files and provides lookup methods.
    """

    def __init__(self):
        self._classes: Dict[str, ClassTemplate] = {}
        self._races: Dict[str, RaceTemplate] = {}

    def register_class(self, template: ClassTemplate) -> None:
        """Register a class template."""
        self._classes[template.class_id] = template
        logger.debug(f"Registered class: {template.class_id}")

    def register_race(self, template: RaceTemplate) -> None:
        """Register a race template."""
        self._races[template.race_id] = template
        logger.debug(f"Registered race: {template.race_id}")

    def get_class(self, class_id: str) -> Optional[ClassTemplate]:
        """Get a class template by ID."""
        return self._classes.get(class_id)

    def get_race(self, race_id: str) -> Optional[RaceTemplate]:
        """Get a race template by ID."""
        return self._races.get(race_id)

    def get_all_classes(self) -> List[ClassTemplate]:
        """Get all registered class templates."""
        return list(self._classes.values())

    def get_all_races(self) -> List[RaceTemplate]:
        """Get all registered race templates."""
        return list(self._races.values())

    def get_class_ids(self) -> List[str]:
        """Get all registered class IDs."""
        return list(self._classes.keys())

    def get_race_ids(self) -> List[str]:
        """Get all registered race IDs."""
        return list(self._races.keys())


def _parse_stat_modifiers(data: Dict[str, Any]) -> Dict[str, int]:
    """Parse stat modifiers from YAML data into a dict."""
    return {
        "strength": data.get("strength", 0),
        "dexterity": data.get("dexterity", 0),
        "constitution": data.get("constitution", 0),
        "intelligence": data.get("intelligence", 0),
        "wisdom": data.get("wisdom", 0),
        "charisma": data.get("charisma", 0),
    }


def _parse_class(data: Dict[str, Any]) -> ClassTemplate:
    """Parse a class definition from YAML data."""
    stat_mods = data.get("stat_modifiers", {})

    return ClassTemplate(
        class_id=data.get("class_id", ""),
        name=data.get("name", "Unknown"),
        description=data.get("description", ""),
        stat_modifiers=_parse_stat_modifiers(stat_mods),
        health_per_level=data.get("health_per_level", 10),
        mana_per_level=data.get("mana_per_level", 5),
        starting_health=data.get("starting_health", 100),
        starting_mana=data.get("starting_mana", 50),
        starting_gold=data.get("starting_gold", 100),
        class_skills=data.get("class_skills", []),
        starting_skills=data.get("starting_skills", []),
        starting_equipment=data.get("starting_equipment", []),
        starting_room=data.get("starting_room", "ravenmoor_square"),
        prime_attribute=data.get("prime_attribute", "strength"),
        armor_proficiency=data.get("armor_proficiency", []),
        weapon_proficiency=data.get("weapon_proficiency", []),
    )


def _parse_race(data: Dict[str, Any]) -> RaceTemplate:
    """Parse a race definition from YAML data."""
    stat_mods = data.get("stat_modifiers", {})

    return RaceTemplate(
        race_id=data.get("race_id", ""),
        name=data.get("name", "Unknown"),
        description=data.get("description", ""),
        stat_modifiers=_parse_stat_modifiers(stat_mods),
        racial_abilities=data.get("racial_abilities", []),
        size=data.get("size", "medium"),
        speed_modifier=data.get("speed_modifier", 100),
        infravision=data.get("infravision", False),
        darkvision=data.get("darkvision", False),
        resistances=data.get("resistances", {}),
        languages=data.get("languages", ["common"]),
        lifespan=data.get("lifespan", "average"),
        starting_room_override=data.get("starting_room_override"),
    )


def load_character_definitions(world_path: str) -> CharacterDefinitionRegistry:
    """
    Load class and race definitions from YAML files.

    Expected structure:
        world/
            classes/
                base.yaml      # Class definitions
            races/
                base.yaml      # Race definitions

    Returns a populated CharacterDefinitionRegistry.
    """
    registry = CharacterDefinitionRegistry()
    world = Path(world_path)

    # Load classes
    classes_path = world / "classes"
    if classes_path.exists():
        for yaml_file in classes_path.glob("*.yaml"):
            try:
                with open(yaml_file, "r") as f:
                    data = yaml.safe_load(f)

                if data and "classes" in data:
                    for class_data in data["classes"]:
                        try:
                            template = _parse_class(class_data)
                            registry.register_class(template)
                        except Exception as e:
                            logger.error(f"Error parsing class in {yaml_file}: {e}")
            except Exception as e:
                logger.error(f"Error loading {yaml_file}: {e}")

    # Load races
    races_path = world / "races"
    if races_path.exists():
        for yaml_file in races_path.glob("*.yaml"):
            try:
                with open(yaml_file, "r") as f:
                    data = yaml.safe_load(f)

                if data and "races" in data:
                    for race_data in data["races"]:
                        try:
                            template = _parse_race(race_data)
                            registry.register_race(template)
                        except Exception as e:
                            logger.error(f"Error parsing race in {yaml_file}: {e}")
            except Exception as e:
                logger.error(f"Error loading {yaml_file}: {e}")

    logger.info(
        f"Loaded character definitions: "
        f"{len(registry.get_all_classes())} classes, "
        f"{len(registry.get_all_races())} races"
    )

    return registry


# Global registry instance
_character_registry: Optional[CharacterDefinitionRegistry] = None


def get_character_registry() -> CharacterDefinitionRegistry:
    """Get the global character definition registry."""
    global _character_registry
    if _character_registry is None:
        _character_registry = CharacterDefinitionRegistry()
    return _character_registry


def initialize_character_registry(world_path: str) -> CharacterDefinitionRegistry:
    """Initialize the global character registry from YAML files."""
    global _character_registry
    _character_registry = load_character_definitions(world_path)
    return _character_registry
