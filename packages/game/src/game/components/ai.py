"""
AI Components

Define mob behavior, personality, and dialogue systems.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum
from datetime import datetime

from core import EntityId, ComponentData


class BehaviorType(str, Enum):
    """Basic behavior patterns."""

    PASSIVE = "passive"  # Won't attack unless attacked
    AGGRESSIVE = "aggressive"  # Attacks on sight
    DEFENSIVE = "defensive"  # Defends territory
    FRIENDLY = "friendly"  # Won't attack, may help players
    COWARDLY = "cowardly"  # Flees when damaged


class CombatStyle(str, Enum):
    """How the mob fights."""

    BERSERKER = "berserker"  # All-out attack
    TACTICIAN = "tactician"  # Balanced, uses skills
    DEFENDER = "defender"  # Defensive, counter-attacks
    AMBUSHER = "ambusher"  # High burst, retreat
    SWARM = "swarm"  # Calls for allies
    CASTER = "caster"  # Uses spells/abilities


class PersonalityTrait(str, Enum):
    """Personality traits for dynamic mobs."""

    AGGRESSIVE = "aggressive"
    DEFENSIVE = "defensive"
    CUNNING = "cunning"
    COWARDLY = "cowardly"
    HONORABLE = "honorable"
    SADISTIC = "sadistic"
    PROTECTIVE = "protective"
    TERRITORIAL = "territorial"
    CURIOUS = "curious"
    GREEDY = "greedy"


@dataclass
class AIData(ComponentData):
    """
    Base AI behavior configuration.
    """

    # Basic behavior
    behavior_type: BehaviorType = BehaviorType.PASSIVE
    combat_style: CombatStyle = CombatStyle.TACTICIAN

    # Movement
    home_room: Optional[EntityId] = None  # Where to return
    patrol_path: List[EntityId] = field(default_factory=list)  # Rooms to patrol
    current_patrol_index: int = 0
    wander_radius: int = 3  # Max rooms from home

    # Combat
    aggro_radius: int = 0  # 0 = won't aggro, rooms away to detect
    flee_threshold: float = 0.2  # Health % to start fleeing
    assist_allies: bool = True  # Help nearby allies in combat

    # Skills/Abilities
    abilities: List[str] = field(default_factory=list)  # Skill IDs this mob can use
    ability_cooldowns: Dict[str, datetime] = field(default_factory=dict)  # skill_id -> last_used
    preferred_abilities: List[str] = field(default_factory=list)  # Priority order for skill selection

    # Targeting
    current_target: Optional[EntityId] = None
    hate_list: Dict[str, int] = field(default_factory=dict)  # entity_id -> hate amount

    # Timing
    last_action_time: Optional[datetime] = None
    action_cooldown_s: float = 2.0

    # Pending skill action (set by AI system, consumed by SkillExecutionSystem)
    pending_skill_id: Optional[str] = None
    pending_skill_target: Optional[EntityId] = None

    def get_highest_threat(self) -> Optional[str]:
        """Get entity with highest hate."""
        if not self.hate_list:
            return None
        return max(self.hate_list.keys(), key=lambda k: self.hate_list[k])

    def add_hate(self, entity_id: str, amount: int) -> None:
        """Add hate toward an entity."""
        current = self.hate_list.get(entity_id, 0)
        self.hate_list[entity_id] = current + amount

    def reduce_hate(self, entity_id: str, amount: int) -> None:
        """Reduce hate, remove if zero."""
        if entity_id in self.hate_list:
            self.hate_list[entity_id] = max(0, self.hate_list[entity_id] - amount)
            if self.hate_list[entity_id] == 0:
                del self.hate_list[entity_id]

    def clear_hate(self) -> None:
        """Clear all hate."""
        self.hate_list.clear()

    def should_flee(self, current_health_percent: float) -> bool:
        """Check if should flee based on health."""
        if self.behavior_type == BehaviorType.COWARDLY:
            return current_health_percent < self.flee_threshold * 1.5
        return current_health_percent < self.flee_threshold

    def has_abilities(self) -> bool:
        """Check if this mob has any abilities."""
        return len(self.abilities) > 0

    def get_ready_abilities(self, current_time: Optional[datetime] = None) -> List[str]:
        """Get list of abilities not on cooldown."""
        if current_time is None:
            current_time = datetime.utcnow()

        ready = []
        for skill_id in self.abilities:
            if skill_id not in self.ability_cooldowns:
                ready.append(skill_id)
            elif current_time >= self.ability_cooldowns[skill_id]:
                ready.append(skill_id)

        return ready

    def is_ability_ready(self, skill_id: str, current_time: Optional[datetime] = None) -> bool:
        """Check if a specific ability is ready."""
        if skill_id not in self.abilities:
            return False
        if skill_id not in self.ability_cooldowns:
            return True
        if current_time is None:
            current_time = datetime.utcnow()
        return current_time >= self.ability_cooldowns[skill_id]

    def set_ability_cooldown(self, skill_id: str, cooldown_seconds: float) -> None:
        """Put an ability on cooldown."""
        from datetime import timedelta
        self.ability_cooldowns[skill_id] = datetime.utcnow() + timedelta(seconds=cooldown_seconds)

    def clear_pending_skill(self) -> Optional[str]:
        """Clear and return the pending skill."""
        skill_id = self.pending_skill_id
        self.pending_skill_id = None
        self.pending_skill_target = None
        return skill_id

    def set_pending_skill(self, skill_id: str, target: Optional[EntityId] = None) -> None:
        """Set a skill to be executed."""
        self.pending_skill_id = skill_id
        self.pending_skill_target = target


@dataclass
class StaticAIData(AIData):
    """
    AI for template-defined (static) mobs.
    """

    template_id: str = ""

    # Script hooks: event_name -> script/action
    script_hooks: Dict[str, str] = field(default_factory=dict)
    # Events: on_spawn, on_death, on_combat_start, on_combat_end,
    #         on_damaged, on_player_enter, on_player_leave, on_say


@dataclass
class DynamicAIData(AIData):
    """
    AI for LLM-generated mobs with personality.
    """

    # Personality
    personality_traits: List[PersonalityTrait] = field(default_factory=list)
    personality_prompt: str = ""  # Description for LLM

    # Memory/context for LLM
    memory_context: List[str] = field(default_factory=list)
    memory_limit: int = 10

    # Dialogue style
    dialogue_style: str = ""  # How the mob speaks

    # Combat taunts
    combat_taunts: List[str] = field(default_factory=list)
    death_message: str = ""

    # Idle behaviors
    idle_behaviors: List[str] = field(default_factory=list)

    # LLM settings
    generation_temperature: float = 0.7

    def add_memory(self, memory: str) -> None:
        """Add a memory, maintaining limit."""
        self.memory_context.append(memory)
        if len(self.memory_context) > self.memory_limit:
            self.memory_context.pop(0)

    def get_combat_taunt(self) -> Optional[str]:
        """Get a random combat taunt."""
        if not self.combat_taunts:
            return None
        import random

        return random.choice(self.combat_taunts)


@dataclass
class DialogueData(ComponentData):
    """
    Dialogue/conversation capabilities for NPCs.
    """

    # Basic responses
    greeting: str = "Hello, traveler."
    farewell: str = "Farewell."

    # Topic -> response mapping
    topics: Dict[str, str] = field(default_factory=dict)

    # Special flags
    is_quest_giver: bool = False
    is_merchant: bool = False
    is_trainer: bool = False
    is_banker: bool = False

    # Shop inventory (template IDs) if merchant
    shop_items: List[str] = field(default_factory=list)

    # Trainable skills if trainer
    trainable_skills: List[str] = field(default_factory=list)

    # =========================================================================
    # Dynamic Quest Generation (Stage 29)
    # =========================================================================

    # If True, this NPC can generate dynamic quests via LLM
    can_generate_quests: bool = False

    # Zones this NPC can offer quests for (empty = current zone only)
    quest_zones: List[str] = field(default_factory=list)

    # NPC personality/role for quest flavor text
    quest_personality: str = ""

    # NPC faction for reputation-based quests
    quest_faction: Optional[str] = None

    # Preferred quest archetypes for this NPC (empty = use zone defaults)
    # Values: "combat", "exploration", "gathering", "delivery", "investigation", etc.
    preferred_quest_types: List[str] = field(default_factory=list)

    def get_response(self, topic: str) -> Optional[str]:
        """Get response for a topic."""
        topic = topic.lower()
        # Check exact match
        if topic in self.topics:
            return self.topics[topic]
        # Check partial match
        for key, response in self.topics.items():
            if topic in key or key in topic:
                return response
        return None
