"""
Personality Engine for Mob Behavior

Translates mob personality traits into concrete behavioral decisions
for combat tactics, dialogue style, and general behavior.
"""

import logging
import random
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from llm.schemas import MobPersonality, CombatStyle, PersonalityTrait

logger = logging.getLogger(__name__)


class CombatAction(str, Enum):
    """Possible combat actions a mob can take."""

    ATTACK = "attack"
    DEFEND = "defend"
    SPECIAL_ABILITY = "special_ability"
    FLEE = "flee"
    CALL_FOR_HELP = "call_for_help"
    TAUNT = "taunt"
    WAIT = "wait"
    HEAL = "heal"


class DialogueIntent(str, Enum):
    """Intent behind mob dialogue."""

    GREETING = "greeting"
    THREAT = "threat"
    BARGAIN = "bargain"
    INFORMATION = "information"
    DISMISS = "dismiss"
    CONFUSION = "confusion"
    FEAR = "fear"


@dataclass
class CombatDecision:
    """A combat decision made by the personality engine."""

    action: CombatAction
    target: Optional[str] = None  # Entity ID of target
    ability_name: Optional[str] = None  # If using special ability
    message: Optional[str] = None  # Combat message to display
    priority: float = 1.0  # How strongly the mob wants this action


@dataclass
class AbilityInfo:
    """Information about an available ability for AI decision making."""

    skill_id: str
    name: str
    mana_cost: int
    stamina_cost: int
    category: str  # combat, magic, healing
    is_offensive: bool
    is_healing: bool
    is_buff: bool
    is_aoe: bool
    cooldown_ready: bool


@dataclass
class CombatContext:
    """Context for making combat decisions."""

    mob_health_pct: float  # 0.0 to 1.0
    target_health_pct: float
    mob_mana_pct: float
    mob_stamina_pct: float = 1.0
    round_number: int = 0
    allies_nearby: int = 0
    enemies_nearby: int = 1
    has_special_abilities: bool = False
    special_ability_ready: bool = False
    is_ambush: bool = False
    mob_is_leader: bool = False

    # Available abilities with details
    available_abilities: list[AbilityInfo] = None  # type: ignore

    def __post_init__(self):
        if self.available_abilities is None:
            self.available_abilities = []


class PersonalityEngine:
    """
    Engine that translates personality traits into behavior.

    Takes a mob's personality profile and current context to determine
    what actions the mob should take in combat or dialogue.
    """

    # Combat style modifiers
    STYLE_ATTACK_WEIGHTS = {
        CombatStyle.AGGRESSIVE: 1.5,
        CombatStyle.DEFENSIVE: 0.7,
        CombatStyle.TACTICAL: 1.0,
        CombatStyle.BERSERKER: 2.0,
        CombatStyle.COWARDLY: 0.5,
        CombatStyle.RANGED: 0.8,
        CombatStyle.MAGICAL: 0.6,
        CombatStyle.SUPPORT: 0.4,
    }

    STYLE_DEFEND_WEIGHTS = {
        CombatStyle.AGGRESSIVE: 0.3,
        CombatStyle.DEFENSIVE: 1.5,
        CombatStyle.TACTICAL: 1.0,
        CombatStyle.BERSERKER: 0.1,
        CombatStyle.COWARDLY: 1.2,
        CombatStyle.RANGED: 0.5,
        CombatStyle.MAGICAL: 0.8,
        CombatStyle.SUPPORT: 1.3,
    }

    STYLE_FLEE_THRESHOLDS = {
        CombatStyle.AGGRESSIVE: 0.1,
        CombatStyle.DEFENSIVE: 0.3,
        CombatStyle.TACTICAL: 0.25,
        CombatStyle.BERSERKER: 0.0,  # Never flees
        CombatStyle.COWARDLY: 0.5,
        CombatStyle.RANGED: 0.35,
        CombatStyle.MAGICAL: 0.3,
        CombatStyle.SUPPORT: 0.4,
    }

    def __init__(self, personality: MobPersonality):
        self.personality = personality

    def decide_combat_action(self, context: CombatContext) -> CombatDecision:
        """
        Decide what combat action the mob should take.

        Considers personality, combat style, and current situation.
        """
        # Check flee condition first
        if self._should_flee(context):
            return CombatDecision(
                action=CombatAction.FLEE,
                message=self._get_flee_message(),
            )

        # Calculate action weights based on personality
        weights = self._calculate_action_weights(context)

        # Add some randomness
        for action in weights:
            weights[action] *= random.uniform(0.8, 1.2)

        # Pick highest weighted action
        best_action = max(weights.keys(), key=lambda a: weights[a])

        return self._create_decision(best_action, context)

    def _should_flee(self, context: CombatContext) -> bool:
        """Determine if mob should flee based on personality and health."""
        base_threshold = self.personality.flee_threshold
        style_modifier = self.STYLE_FLEE_THRESHOLDS.get(self.personality.combat_style, 0.2)

        # Adjust threshold based on style
        effective_threshold = (base_threshold + style_modifier) / 2

        # Cowards flee earlier if outnumbered
        if PersonalityTrait.HOSTILE not in self.personality.traits:
            if context.enemies_nearby > context.allies_nearby + 1:
                effective_threshold *= 1.3

        # Pride trait reduces flee chance
        if PersonalityTrait.PROUD in self.personality.traits:
            effective_threshold *= 0.7

        return context.mob_health_pct <= effective_threshold

    def _calculate_action_weights(self, context: CombatContext) -> dict[CombatAction, float]:
        """Calculate weights for each possible action."""
        style = self.personality.combat_style

        weights: dict[CombatAction, float] = {
            CombatAction.ATTACK: self.STYLE_ATTACK_WEIGHTS.get(style, 1.0),
            CombatAction.DEFEND: self.STYLE_DEFEND_WEIGHTS.get(style, 1.0),
            CombatAction.SPECIAL_ABILITY: 0.0,
            CombatAction.CALL_FOR_HELP: 0.0,
            CombatAction.TAUNT: 0.0,
            CombatAction.WAIT: 0.1,
            CombatAction.HEAL: 0.0,
        }

        # Special ability weight
        if context.has_special_abilities and context.special_ability_ready:
            if style == CombatStyle.MAGICAL:
                weights[CombatAction.SPECIAL_ABILITY] = 1.8
            elif style == CombatStyle.TACTICAL:
                # Use abilities when advantageous
                if context.target_health_pct < 0.5 or context.mob_health_pct < 0.5:
                    weights[CombatAction.SPECIAL_ABILITY] = 1.5
                else:
                    weights[CombatAction.SPECIAL_ABILITY] = 0.8
            else:
                weights[CombatAction.SPECIAL_ABILITY] = 1.0

        # Support style prefers healing when hurt
        if style == CombatStyle.SUPPORT and context.mob_health_pct < 0.6:
            weights[CombatAction.HEAL] = 1.5

        # Call for help if losing and not alone
        if context.mob_health_pct < 0.4 and context.allies_nearby > 0:
            weights[CombatAction.CALL_FOR_HELP] = 0.8

        # Taunt for aggressive/proud mobs
        if PersonalityTrait.PROUD in self.personality.traits:
            weights[CombatAction.TAUNT] = 0.5
        if style == CombatStyle.AGGRESSIVE:
            weights[CombatAction.TAUNT] = 0.4

        # Berserkers attack more when hurt
        if style == CombatStyle.BERSERKER and context.mob_health_pct < 0.5:
            weights[CombatAction.ATTACK] *= 1.5

        # Defensive mobs defend more when low
        if style == CombatStyle.DEFENSIVE and context.mob_health_pct < 0.4:
            weights[CombatAction.DEFEND] *= 1.5

        # Cunning trait: adapt to enemy health
        if PersonalityTrait.CUNNING in self.personality.traits:
            if context.target_health_pct < 0.3:
                weights[CombatAction.ATTACK] *= 1.3  # Go for the kill
            elif context.mob_health_pct < 0.3:
                weights[CombatAction.DEFEND] *= 1.3  # Play it safe

        return weights

    def _create_decision(self, action: CombatAction, context: CombatContext) -> CombatDecision:
        """Create a decision with appropriate details."""
        message = self._get_action_message(action)

        if action == CombatAction.SPECIAL_ABILITY:
            # Select the best ability from available ones
            ability = self._select_ability(context)
            if ability:
                return CombatDecision(
                    action=action,
                    ability_name=ability.skill_id,
                    message=f"uses {ability.name}!",
                )
            else:
                # No ability available, fall back to attack
                return CombatDecision(
                    action=CombatAction.ATTACK,
                    message=self._get_action_message(CombatAction.ATTACK),
                )

        if action == CombatAction.HEAL:
            # Find a healing ability
            healing_abilities = [
                a for a in context.available_abilities
                if a.is_healing and a.cooldown_ready
            ]
            if healing_abilities:
                ability = healing_abilities[0]
                return CombatDecision(
                    action=action,
                    ability_name=ability.skill_id,
                    message=f"casts {ability.name}!",
                )

        return CombatDecision(action=action, message=message)

    def _select_ability(self, context: CombatContext) -> Optional[AbilityInfo]:
        """
        Select the best ability to use based on combat style and context.

        Returns None if no suitable ability is available.
        """
        if not context.available_abilities:
            return None

        style = self.personality.combat_style
        ready_abilities = [a for a in context.available_abilities if a.cooldown_ready]

        if not ready_abilities:
            return None

        # Filter by resource availability (simplified - assume we can afford any ready ability)
        affordable = ready_abilities

        if not affordable:
            return None

        # Score each ability based on combat style and situation
        scored: list[tuple[AbilityInfo, float]] = []

        for ability in affordable:
            score = 1.0

            # Magical styles prefer magic abilities
            if style == CombatStyle.MAGICAL:
                if ability.category == "magic":
                    score *= 1.8
                elif ability.category == "healing":
                    score *= 1.2

            # Support styles prefer healing when hurt
            elif style == CombatStyle.SUPPORT:
                if ability.is_healing and context.mob_health_pct < 0.6:
                    score *= 2.0
                elif ability.is_buff:
                    score *= 1.5

            # Aggressive/Berserker prefer offensive abilities
            elif style in (CombatStyle.AGGRESSIVE, CombatStyle.BERSERKER):
                if ability.is_offensive:
                    score *= 1.5
                    # Extra bonus for AOE when outnumbered
                    if ability.is_aoe and context.enemies_nearby > 1:
                        score *= 1.3

            # Tactical style adapts to situation
            elif style == CombatStyle.TACTICAL:
                # Low health: prefer healing
                if context.mob_health_pct < 0.4 and ability.is_healing:
                    score *= 2.0
                # Target low health: prefer offensive finishers
                elif context.target_health_pct < 0.3 and ability.is_offensive:
                    score *= 1.5
                # Many enemies: prefer AOE
                elif context.enemies_nearby > 2 and ability.is_aoe:
                    score *= 1.8

            # Ranged style prefers distance attacks
            elif style == CombatStyle.RANGED:
                if ability.category == "magic" or ability.is_offensive:
                    score *= 1.4

            # Add some randomness
            score *= random.uniform(0.9, 1.1)

            scored.append((ability, score))

        # Return highest scored ability
        if scored:
            scored.sort(key=lambda x: x[1], reverse=True)
            return scored[0][0]

        return None

    def _get_flee_message(self) -> str:
        """Get an appropriate flee message based on personality."""
        style = self.personality.combat_style
        traits = self.personality.traits

        if PersonalityTrait.PROUD in traits:
            return "snarls and retreats, vowing revenge!"
        elif PersonalityTrait.CUNNING in traits:
            return "slips away, seeking a better opportunity."
        elif style == CombatStyle.COWARDLY:
            return "shrieks in terror and flees!"
        else:
            return "decides to withdraw from the fight."

    def _get_action_message(self, action: CombatAction) -> str:
        """Get a combat message for the action."""
        style = self.personality.combat_style
        traits = self.personality.traits

        if action == CombatAction.ATTACK:
            if style == CombatStyle.BERSERKER:
                return "attacks with reckless fury!"
            elif style == CombatStyle.TACTICAL:
                return "strikes with precision."
            elif PersonalityTrait.SAVAGE in traits:
                return "attacks savagely!"
            else:
                return "attacks!"

        elif action == CombatAction.DEFEND:
            if style == CombatStyle.DEFENSIVE:
                return "raises its guard expertly."
            elif PersonalityTrait.CUNNING in traits:
                return "watches carefully for an opening."
            else:
                return "takes a defensive stance."

        elif action == CombatAction.TAUNT:
            if PersonalityTrait.PROUD in traits:
                return "boasts of its superiority!"
            elif PersonalityTrait.HOSTILE in traits:
                return "hurls insults!"
            else:
                return "taunts its opponent."

        elif action == CombatAction.CALL_FOR_HELP:
            return "calls out for reinforcements!"

        elif action == CombatAction.HEAL:
            return "tends to its wounds."

        return ""

    # =========================================================================
    # Dialogue Decisions
    # =========================================================================

    def decide_dialogue_response(
        self,
        player_intent: str,
        relationship: str = "neutral",
    ) -> DialogueIntent:
        """
        Decide how the mob should respond to player dialogue.

        Args:
            player_intent: What the player seems to want (greeting, question, etc.)
            relationship: Current relationship (friendly, neutral, hostile)
        """
        traits = self.personality.traits

        # Hostile mobs tend toward threats
        if PersonalityTrait.HOSTILE in traits:
            if relationship == "hostile":
                return DialogueIntent.THREAT
            return DialogueIntent.DISMISS

        # Friendly mobs are more helpful
        if PersonalityTrait.FRIENDLY in traits:
            if player_intent == "question":
                return DialogueIntent.INFORMATION
            return DialogueIntent.GREETING

        # Greedy mobs try to bargain
        if PersonalityTrait.GREEDY in traits:
            return DialogueIntent.BARGAIN

        # Curious mobs want to learn
        if PersonalityTrait.CURIOUS in traits:
            return DialogueIntent.INFORMATION

        # Proud mobs are dismissive
        if PersonalityTrait.PROUD in traits:
            return DialogueIntent.DISMISS

        # Default based on relationship
        if relationship == "hostile":
            return DialogueIntent.THREAT
        elif relationship == "friendly":
            return DialogueIntent.GREETING
        else:
            return DialogueIntent.GREETING

    def get_dialogue_style_prompt(self) -> str:
        """Get a prompt describing how this mob should speak."""
        style_parts = []

        # Base style from personality
        style_parts.append(self.personality.dialogue_style)

        # Add trait influences
        for trait in self.personality.traits:
            if trait == PersonalityTrait.HOSTILE:
                style_parts.append("Aggressive and threatening tone.")
            elif trait == PersonalityTrait.FRIENDLY:
                style_parts.append("Warm and welcoming tone.")
            elif trait == PersonalityTrait.CUNNING:
                style_parts.append("Cryptic and calculating manner of speech.")
            elif trait == PersonalityTrait.NOBLE:
                style_parts.append("Formal and dignified language.")
            elif trait == PersonalityTrait.SAVAGE:
                style_parts.append("Broken, primitive speech patterns.")
            elif trait == PersonalityTrait.WISE:
                style_parts.append("Speaks in thoughtful, measured tones.")
            elif trait == PersonalityTrait.PLAYFUL:
                style_parts.append("Mischievous and teasing manner.")

        return " ".join(style_parts)
