"""
LLM Dungeon Master System

An intelligent game master system that uses LLMs for:
- Dynamic NPC dialogue based on personality and knowledge base
- Combat narration (attack descriptions, critical hits, deaths)
- Room atmosphere descriptions
- Effect descriptions (buffs, debuffs, status effects)
- Dynamic event narration

Key design principles:
1. Content buffering with high/low watermarks for responsiveness
2. Dice rolling handled by game code, not LLM
3. LLM generates descriptions/narration around mechanics
4. Personality and knowledge bases define NPC behavior
5. Generated content cached for reuse

Based on research:
- CALYPSO: LLMs as Dungeon Master's Assistants
- Function Calling for AI Game Masters
- AI Dungeon architecture patterns
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
import asyncio
import logging
import random
import hashlib

import ray

from .agents import combat_agent, dialogue_agent
from .cache import create_cached_agent, CachedAgent
from .schemas import (
    CombatNarration,
    CombatNarrationContext as AgentCombatContext,
    DialogueResponse,
    DialogueContext as AgentDialogueContext,
    NPCPersonality as AgentNPCPersonality,
)
from .schemas.mob import DamageType
from .schemas.dialogue import NPCMood, SpeechStyle as AgentSpeechStyle

logger = logging.getLogger(__name__)


# =============================================================================
# Content Types and Requests
# =============================================================================


class NarrationCategory(str, Enum):
    """Categories of narration the DM can generate."""

    COMBAT_ATTACK = "combat_attack"
    COMBAT_DEFEND = "combat_defend"
    COMBAT_MISS = "combat_miss"
    COMBAT_CRITICAL = "combat_critical"
    COMBAT_DEATH = "combat_death"
    COMBAT_FLEE = "combat_flee"

    SKILL_USE = "skill_use"
    SKILL_SUCCESS = "skill_success"
    SKILL_FAILURE = "skill_failure"

    EFFECT_APPLY = "effect_apply"
    EFFECT_TICK = "effect_tick"
    EFFECT_EXPIRE = "effect_expire"

    DIALOGUE = "dialogue"
    DIALOGUE_GREETING = "dialogue_greeting"
    DIALOGUE_TOPIC = "dialogue_topic"
    DIALOGUE_FAREWELL = "dialogue_farewell"

    ROOM_AMBIENT = "room_ambient"
    ROOM_DESCRIPTION = "room_description"

    EVENT = "event"


@dataclass
class NarrationRequest:
    """Request for narration from the DM."""

    category: NarrationCategory
    context: Dict[str, Any]

    # For caching - requests with same key return cached results
    cache_key: Optional[str] = None

    # Priority - higher priority requests processed first
    priority: int = 50

    # Timeout for this specific request
    timeout_ms: int = 5000


@dataclass
class NarrationResponse:
    """Response containing generated narration."""

    text: str
    category: NarrationCategory
    generated_at: datetime = field(default_factory=datetime.utcnow)
    from_cache: bool = False
    latency_ms: float = 0


# =============================================================================
# Personality and Knowledge Base
# =============================================================================


class PersonalityTrait(str, Enum):
    """Core personality traits that influence dialogue."""

    FRIENDLY = "friendly"
    HOSTILE = "hostile"
    MYSTERIOUS = "mysterious"
    HELPFUL = "helpful"
    GRUFF = "gruff"
    CHEERFUL = "cheerful"
    SUSPICIOUS = "suspicious"
    WISE = "wise"
    FOOLISH = "foolish"
    BRAVE = "brave"
    COWARDLY = "cowardly"
    GREEDY = "greedy"
    GENEROUS = "generous"
    PROUD = "proud"
    HUMBLE = "humble"


class SpeechStyle(str, Enum):
    """How the NPC speaks."""

    FORMAL = "formal"
    CASUAL = "casual"
    ARCHAIC = "archaic"
    TERSE = "terse"
    VERBOSE = "verbose"
    POETIC = "poetic"
    CRUDE = "crude"
    SCHOLARLY = "scholarly"
    THEATRICAL = "theatrical"


@dataclass
class KnowledgeEntry:
    """A piece of knowledge an NPC can discuss."""

    topic: str  # Topic keyword/phrase
    knowledge: str  # What the NPC knows
    confidentiality: int = 0  # 0 = shares freely, higher = harder to get
    triggers: List[str] = field(default_factory=list)  # Keywords that trigger this


@dataclass
class NPCPersonality:
    """
    Complete personality definition for an NPC.

    This is loaded from YAML and used by the DM to generate consistent dialogue.
    """

    # Core traits
    traits: List[PersonalityTrait] = field(default_factory=list)
    speech_style: SpeechStyle = SpeechStyle.CASUAL

    # Background and motivation
    background: str = ""  # Brief backstory
    motivation: str = ""  # What drives this NPC
    secrets: List[str] = field(default_factory=list)  # Hidden info

    # Knowledge base
    knowledge: List[KnowledgeEntry] = field(default_factory=list)

    # Dialogue patterns (for fallback/guidance)
    catchphrases: List[str] = field(default_factory=list)
    verbal_tics: List[str] = field(default_factory=list)  # "you know", "hmm"

    # Relationships
    likes: List[str] = field(default_factory=list)  # Topics they enjoy
    dislikes: List[str] = field(default_factory=list)  # Topics they avoid
    allies: List[str] = field(default_factory=list)  # NPC IDs
    enemies: List[str] = field(default_factory=list)  # NPC IDs

    # Combat style for narration
    combat_style_description: str = ""  # "fights with brutal efficiency"

    def get_trait_prompt(self) -> str:
        """Get prompt fragment describing personality."""
        traits_str = ", ".join(t.value for t in self.traits)
        return (
            f"Personality: {traits_str}. "
            f"Speech style: {self.speech_style.value}. "
            f"Background: {self.background}"
        )

    def get_knowledge_for_topic(self, topic: str) -> Optional[KnowledgeEntry]:
        """Find knowledge entry matching a topic."""
        topic_lower = topic.lower()
        for entry in self.knowledge:
            if topic_lower in entry.topic.lower():
                return entry
            for trigger in entry.triggers:
                if topic_lower in trigger.lower():
                    return entry
        return None


# =============================================================================
# Content Buffer with Watermarks
# =============================================================================


@dataclass
class BufferConfig:
    """Configuration for a content buffer."""

    category: NarrationCategory
    low_watermark: int = 3  # Trigger refill when below this
    high_watermark: int = 10  # Fill up to this level
    max_size: int = 20  # Never exceed this
    ttl_seconds: int = 3600  # Cached items expire after this


@dataclass
class BufferedContent:
    """A piece of buffered content."""

    text: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    context_hash: str = ""  # Hash of context for matching
    use_count: int = 0


class ContentBuffer:
    """
    Buffers pre-generated content for instant delivery.

    When buffer falls below low_watermark, background generation starts.
    Content is reused if context matches (with variation).
    """

    def __init__(self, config: BufferConfig):
        self._config = config
        self._buffer: List[BufferedContent] = []
        self._lock = asyncio.Lock()

    @property
    def category(self) -> NarrationCategory:
        return self._config.category

    @property
    def current_size(self) -> int:
        return len(self._buffer)

    @property
    def needs_refill(self) -> bool:
        return self.current_size < self._config.low_watermark

    @property
    def refill_count(self) -> int:
        """How many items needed to reach high watermark."""
        return max(0, self._config.high_watermark - self.current_size)

    async def get(self, context_hash: Optional[str] = None) -> Optional[BufferedContent]:
        """Get content from buffer, preferring context match."""
        async with self._lock:
            if not self._buffer:
                return None

            # Try to find context-matching content first
            if context_hash:
                for i, item in enumerate(self._buffer):
                    if item.context_hash == context_hash:
                        item.use_count += 1
                        if item.use_count >= 3:
                            # Remove after 3 uses to encourage variety
                            self._buffer.pop(i)
                        return item

            # Return random item
            idx = random.randrange(len(self._buffer))
            item = self._buffer[idx]
            item.use_count += 1
            if item.use_count >= 3:
                self._buffer.pop(idx)
            return item

    async def add(self, content: str, context_hash: str = "") -> None:
        """Add content to buffer if not at max."""
        async with self._lock:
            if len(self._buffer) >= self._config.max_size:
                return

            self._buffer.append(BufferedContent(
                text=content,
                context_hash=context_hash,
            ))

    async def add_batch(self, items: List[tuple]) -> None:
        """Add multiple (content, context_hash) items."""
        async with self._lock:
            for text, context_hash in items:
                if len(self._buffer) >= self._config.max_size:
                    break
                self._buffer.append(BufferedContent(
                    text=text,
                    context_hash=context_hash,
                ))

    async def clean_expired(self) -> int:
        """Remove expired content. Returns count removed."""
        async with self._lock:
            now = datetime.utcnow()
            ttl = timedelta(seconds=self._config.ttl_seconds)
            before = len(self._buffer)
            self._buffer = [
                item for item in self._buffer
                if now - item.created_at < ttl
            ]
            return before - len(self._buffer)


# =============================================================================
# Combat Narration Context
# =============================================================================


@dataclass
class CombatNarrationContext:
    """Context for generating combat narration."""

    attacker_name: str
    attacker_weapon: str = "fists"
    attacker_personality: Optional[NPCPersonality] = None

    defender_name: str = ""
    defender_armor: str = ""
    defender_personality: Optional[NPCPersonality] = None

    # Dice results (already rolled by game)
    damage: int = 0
    damage_type: str = "physical"
    is_critical: bool = False
    is_miss: bool = False
    is_kill: bool = False

    # Active effects
    attacker_effects: List[str] = field(default_factory=list)
    defender_effects: List[str] = field(default_factory=list)

    # Skill/ability used
    skill_name: Optional[str] = None

    # Environment
    room_type: str = "indoor"
    weather: str = "clear"

    def to_cache_key(self) -> str:
        """Generate cache key for similar combats."""
        key_parts = [
            self.damage_type,
            str(self.is_critical),
            str(self.is_miss),
            str(self.is_kill),
            self.skill_name or "basic",
        ]
        return hashlib.md5(":".join(key_parts).encode()).hexdigest()[:12]


@dataclass
class DialogueContext:
    """Context for generating NPC dialogue."""

    npc_name: str
    npc_personality: NPCPersonality
    player_name: str
    player_input: str

    # Conversation state
    topic: Optional[str] = None
    conversation_history: List[str] = field(default_factory=list)

    # World state
    time_of_day: str = "day"
    location: str = ""
    recent_events: List[str] = field(default_factory=list)

    # Player reputation/relationship
    relationship_level: int = 0  # -100 to 100

    def to_cache_key(self) -> str:
        """Generate cache key for similar dialogues."""
        key_parts = [
            self.npc_name,
            self.topic or "general",
            str(self.relationship_level // 20),  # Bucket relationships
        ]
        return hashlib.md5(":".join(key_parts).encode()).hexdigest()[:12]


# =============================================================================
# Dungeon Master Actor
# =============================================================================


@ray.remote
class DungeonMaster:
    """
    Ray actor that serves as the LLM-powered Dungeon Master.

    Responsibilities:
    - Generate contextual combat narration
    - Handle NPC dialogue with personality
    - Provide atmospheric descriptions
    - Buffer content for responsiveness

    The DM does NOT roll dice - that's handled by game systems.
    The DM describes what happens after dice are rolled.
    """

    def __init__(self, provider_config: Dict[str, Any]):
        self._provider_config = provider_config
        self._provider = None  # Lazy init

        # PydanticAI agents with caching
        self._combat_agent: CachedAgent = create_cached_agent(
            combat_agent,
            ttl_seconds=1800,  # 30 min cache for combat narration
            cache_enabled=True,
        )
        self._dialogue_agent: CachedAgent = create_cached_agent(
            dialogue_agent,
            ttl_seconds=300,  # 5 min cache for dialogue (more dynamic)
            cache_enabled=True,
        )

        # Content buffers by category
        self._buffers: Dict[NarrationCategory, ContentBuffer] = {}
        self._init_buffers()

        # Narration cache (for reusing exact matches)
        self._cache: Dict[str, NarrationResponse] = {}
        self._cache_max_size = 1000
        self._cache_ttl = timedelta(hours=1)

        # NPC personality cache
        self._personalities: Dict[str, NPCPersonality] = {}

        # Background refill task
        self._refill_task: Optional[asyncio.Task] = None
        self._running = False

        # Stats
        self._stats = {
            "cache_hits": 0,
            "cache_misses": 0,
            "buffer_hits": 0,
            "buffer_misses": 0,
            "generations": 0,
            "agent_calls": 0,
            "errors": 0,
        }

        logger.info("DungeonMaster initialized with PydanticAI agents")

    def _init_buffers(self) -> None:
        """Initialize content buffers with default configs."""
        buffer_configs = [
            BufferConfig(NarrationCategory.COMBAT_ATTACK, low_watermark=5, high_watermark=15),
            BufferConfig(NarrationCategory.COMBAT_MISS, low_watermark=5, high_watermark=15),
            BufferConfig(NarrationCategory.COMBAT_CRITICAL, low_watermark=3, high_watermark=10),
            BufferConfig(NarrationCategory.COMBAT_DEATH, low_watermark=3, high_watermark=10),
            BufferConfig(NarrationCategory.SKILL_USE, low_watermark=5, high_watermark=15),
            BufferConfig(NarrationCategory.EFFECT_APPLY, low_watermark=5, high_watermark=15),
            BufferConfig(NarrationCategory.ROOM_AMBIENT, low_watermark=10, high_watermark=25),
        ]

        for config in buffer_configs:
            self._buffers[config.category] = ContentBuffer(config)

    async def start(self) -> None:
        """Start the DM and background tasks."""
        if self._running:
            return

        self._running = True
        self._refill_task = asyncio.create_task(self._refill_loop())
        logger.info("DungeonMaster started")

    async def stop(self) -> None:
        """Stop the DM."""
        self._running = False
        if self._refill_task:
            self._refill_task.cancel()
            try:
                await self._refill_task
            except asyncio.CancelledError:
                pass
        logger.info("DungeonMaster stopped")

    # =========================================================================
    # Combat Narration
    # =========================================================================

    async def narrate_attack(self, ctx: CombatNarrationContext) -> NarrationResponse:
        """Generate narration for an attack."""
        if ctx.is_kill:
            return await self._get_narration(
                NarrationCategory.COMBAT_DEATH, ctx.to_cache_key(), ctx
            )
        elif ctx.is_miss:
            return await self._get_narration(
                NarrationCategory.COMBAT_MISS, ctx.to_cache_key(), ctx
            )
        elif ctx.is_critical:
            return await self._get_narration(
                NarrationCategory.COMBAT_CRITICAL, ctx.to_cache_key(), ctx
            )
        else:
            return await self._get_narration(
                NarrationCategory.COMBAT_ATTACK, ctx.to_cache_key(), ctx
            )

    async def narrate_skill(
        self, skill_name: str, success: bool, ctx: Dict[str, Any]
    ) -> NarrationResponse:
        """Generate narration for skill use."""
        category = (
            NarrationCategory.SKILL_SUCCESS if success
            else NarrationCategory.SKILL_FAILURE
        )
        cache_key = f"{skill_name}:{success}"
        return await self._get_narration(category, cache_key, ctx)

    async def narrate_effect(
        self, effect_name: str, event_type: str, ctx: Dict[str, Any]
    ) -> NarrationResponse:
        """Generate narration for effect events."""
        if event_type == "apply":
            category = NarrationCategory.EFFECT_APPLY
        elif event_type == "tick":
            category = NarrationCategory.EFFECT_TICK
        else:
            category = NarrationCategory.EFFECT_EXPIRE

        cache_key = f"{effect_name}:{event_type}"
        return await self._get_narration(category, cache_key, ctx)

    # =========================================================================
    # Dialogue
    # =========================================================================

    async def generate_dialogue(self, ctx: DialogueContext) -> NarrationResponse:
        """Generate NPC dialogue based on personality and context."""
        # Check knowledge base for topic
        knowledge = None
        if ctx.topic:
            knowledge = ctx.npc_personality.get_knowledge_for_topic(ctx.topic)

        # Build prompt
        prompt = self._build_dialogue_prompt(ctx, knowledge)

        # Generate (dialogue is usually not buffered - too context-specific)
        start_time = datetime.utcnow()
        try:
            text = await self._generate_text(prompt)
            latency = (datetime.utcnow() - start_time).total_seconds() * 1000

            return NarrationResponse(
                text=text,
                category=NarrationCategory.DIALOGUE,
                latency_ms=latency,
            )
        except Exception as e:
            logger.error(f"Dialogue generation error: {e}")
            self._stats["errors"] += 1
            # Fallback to simple response
            return self._generate_fallback_dialogue(ctx)

    def _build_dialogue_prompt(
        self, ctx: DialogueContext, knowledge: Optional[KnowledgeEntry]
    ) -> str:
        """Build prompt for dialogue generation."""
        personality = ctx.npc_personality

        prompt_parts = [
            f"You are {ctx.npc_name}, an NPC in a fantasy MUD.",
            personality.get_trait_prompt(),
            f"\nThe player {ctx.player_name} says: \"{ctx.player_input}\"",
        ]

        if knowledge:
            prompt_parts.append(
                f"\nYou know about {knowledge.topic}: {knowledge.knowledge}"
            )

        if personality.catchphrases:
            prompt_parts.append(
                f"\nOccasionally use phrases like: {', '.join(personality.catchphrases)}"
            )

        prompt_parts.append(
            "\nRespond in character. Keep response to 1-3 sentences. "
            "Do not break character or mention game mechanics."
        )

        return "\n".join(prompt_parts)

    def _generate_fallback_dialogue(self, ctx: DialogueContext) -> NarrationResponse:
        """Generate simple fallback dialogue without LLM."""
        personality = ctx.npc_personality

        if PersonalityTrait.FRIENDLY in personality.traits:
            text = f"{ctx.npc_name} smiles warmly. \"Good to see you, friend.\""
        elif PersonalityTrait.HOSTILE in personality.traits:
            text = f"{ctx.npc_name} glares. \"What do you want?\""
        elif PersonalityTrait.MYSTERIOUS in personality.traits:
            text = f"{ctx.npc_name} gazes at you thoughtfully. \"Perhaps.\""
        else:
            text = f"{ctx.npc_name} nods in acknowledgment."

        return NarrationResponse(
            text=text,
            category=NarrationCategory.DIALOGUE,
            from_cache=True,
        )

    # =========================================================================
    # Personality Management
    # =========================================================================

    async def register_personality(
        self, npc_id: str, personality: NPCPersonality
    ) -> None:
        """Register an NPC's personality for dialogue."""
        self._personalities[npc_id] = personality
        logger.debug(f"Registered personality for {npc_id}")

    async def get_personality(self, npc_id: str) -> Optional[NPCPersonality]:
        """Get an NPC's registered personality."""
        return self._personalities.get(npc_id)

    async def generate_personality(
        self, npc_name: str, npc_type: str, context: str
    ) -> NPCPersonality:
        """
        Use LLM to generate a personality for an NPC.

        TODO: Implement using PydanticAI agent for structured personality generation.
        Currently returns a default personality as a placeholder.
        """
        # Future: Use a personality generation agent with structured output
        _ = (npc_name, npc_type, context)  # Mark as intentionally unused for now

        try:
            return NPCPersonality(
                traits=[PersonalityTrait.FRIENDLY],
                speech_style=SpeechStyle.CASUAL,
                background=f"A {npc_type} making their way in the world.",
                motivation="Survival and happiness.",
            )
        except Exception as e:
            logger.error(f"Personality generation error: {e}")
            return NPCPersonality()

    # =========================================================================
    # Internal Methods
    # =========================================================================

    async def _get_narration(
        self, category: NarrationCategory, cache_key: str, context: Any
    ) -> NarrationResponse:
        """Get narration, trying cache then buffer then generation."""
        full_cache_key = f"{category.value}:{cache_key}"

        # Check cache
        if full_cache_key in self._cache:
            cached = self._cache[full_cache_key]
            if datetime.utcnow() - cached.generated_at < self._cache_ttl:
                self._stats["cache_hits"] += 1
                cached.from_cache = True
                return cached

        self._stats["cache_misses"] += 1

        # Check buffer
        if category in self._buffers:
            buffered = await self._buffers[category].get(cache_key)
            if buffered:
                self._stats["buffer_hits"] += 1
                response = NarrationResponse(
                    text=buffered.text,
                    category=category,
                    from_cache=True,
                )
                return response

        self._stats["buffer_misses"] += 1

        # Generate fresh
        start_time = datetime.utcnow()
        try:
            prompt = self._build_narration_prompt(category, context)
            text = await self._generate_text(prompt)
            latency = (datetime.utcnow() - start_time).total_seconds() * 1000

            response = NarrationResponse(
                text=text,
                category=category,
                latency_ms=latency,
            )

            # Cache the result
            if len(self._cache) < self._cache_max_size:
                self._cache[full_cache_key] = response

            return response

        except Exception as e:
            logger.error(f"Narration generation error: {e}")
            self._stats["errors"] += 1
            return self._generate_fallback(category, context)

    def _build_narration_prompt(
        self, category: NarrationCategory, context: Any
    ) -> str:
        """Build prompt for narration generation."""
        if isinstance(context, CombatNarrationContext):
            return self._build_combat_prompt(category, context)
        else:
            return self._build_generic_prompt(category, context)

    def _build_combat_prompt(
        self, category: NarrationCategory, ctx: CombatNarrationContext
    ) -> str:
        """Build combat narration prompt."""
        prompts = {
            NarrationCategory.COMBAT_ATTACK: f"""
                Narrate a combat attack:
                {ctx.attacker_name} attacks {ctx.defender_name} with {ctx.attacker_weapon}.
                Damage dealt: {ctx.damage} ({ctx.damage_type})
                Skill used: {ctx.skill_name or 'basic attack'}

                Write 1 vivid sentence describing this attack.
                Use active voice and visceral details.
            """,
            NarrationCategory.COMBAT_MISS: f"""
                Narrate a combat miss:
                {ctx.attacker_name} attacks {ctx.defender_name} but misses.

                Write 1 sentence describing the miss dramatically.
            """,
            NarrationCategory.COMBAT_CRITICAL: f"""
                Narrate a critical hit:
                {ctx.attacker_name} lands a devastating blow on {ctx.defender_name}!
                Damage dealt: {ctx.damage} ({ctx.damage_type})

                Write 1 exciting sentence about this powerful strike.
            """,
            NarrationCategory.COMBAT_DEATH: f"""
                Narrate a death blow:
                {ctx.attacker_name} delivers the killing blow to {ctx.defender_name}.

                Write 1 dramatic sentence describing the final moment.
            """,
        }
        return prompts.get(category, "Generate a short combat description.")

    def _build_generic_prompt(
        self, category: NarrationCategory, context: Dict[str, Any]
    ) -> str:
        """Build generic narration prompt."""
        return f"Generate a short, atmospheric description for: {category.value}"

    def _generate_fallback(
        self, category: NarrationCategory, context: Any
    ) -> NarrationResponse:
        """Generate simple fallback narration without LLM."""
        fallbacks = {
            NarrationCategory.COMBAT_ATTACK: "The attack connects solidly.",
            NarrationCategory.COMBAT_MISS: "The attack goes wide.",
            NarrationCategory.COMBAT_CRITICAL: "A devastating strike!",
            NarrationCategory.COMBAT_DEATH: "The final blow lands.",
            NarrationCategory.SKILL_USE: "The ability activates.",
            NarrationCategory.EFFECT_APPLY: "You feel the effect take hold.",
        }

        return NarrationResponse(
            text=fallbacks.get(category, "Something happens."),
            category=category,
            from_cache=True,
        )

    async def _generate_text(self, prompt: str) -> str:
        """Generate text using the LLM provider (legacy fallback)."""
        # This is a fallback for simple prompts
        # Prefer using agents for structured generation
        self._stats["generations"] += 1
        await asyncio.sleep(0.1)  # Simulate latency
        return "Generated text placeholder"

    async def _generate_combat_narration(
        self, ctx: CombatNarrationContext
    ) -> CombatNarration:
        """Generate combat narration using PydanticAI agent."""
        # Convert internal context to agent context
        agent_ctx = AgentCombatContext(
            attacker_name=ctx.attacker_name,
            attacker_race="unknown",  # Would come from entity data
            attacker_class=None,
            attacker_weapon=ctx.attacker_weapon,
            defender_name=ctx.defender_name,
            defender_race="unknown",
            defender_armor=ctx.defender_armor or None,
            damage_amount=ctx.damage,
            damage_type=DamageType(ctx.damage_type) if ctx.damage_type != "physical" else DamageType.BLUDGEONING,
            is_critical=ctx.is_critical,
            is_miss=ctx.is_miss,
            is_killing_blow=ctx.is_kill,
            combat_round=1,
            attacker_health_percent=100,
            defender_health_percent=50 if not ctx.is_kill else 0,
            skill_used=ctx.skill_name,
            environment_hint=ctx.room_type,
        )

        self._stats["agent_calls"] += 1
        try:
            result = await self._combat_agent.run(
                "Generate combat narration for this attack.",
                deps=agent_ctx,
            )
            return result
        except Exception as e:
            logger.error(f"Combat agent error: {e}")
            self._stats["errors"] += 1
            # Return a minimal fallback
            return CombatNarration(
                attack_description=f"{ctx.attacker_name} attacks {ctx.defender_name}.",
                damage_description=f"The blow deals {ctx.damage} damage.",
            )

    async def _generate_dialogue_response(
        self, ctx: DialogueContext
    ) -> DialogueResponse:
        """Generate dialogue using PydanticAI agent."""
        # Convert internal personality to agent personality
        personality = ctx.npc_personality

        agent_personality = AgentNPCPersonality(
            name=ctx.npc_name,
            role="NPC",
            speech_style=AgentSpeechStyle(personality.speech_style.value) if personality.speech_style else AgentSpeechStyle.CASUAL,
            default_mood=NPCMood.NEUTRAL,
            background=personality.background or "A mysterious figure.",
            motivation=personality.motivation or "Unknown motivations.",
            quirks=personality.verbal_tics[:3] if personality.verbal_tics else [],
            knowledge_topics=[k.topic for k in personality.knowledge[:5]] if personality.knowledge else [],
            catchphrases=personality.catchphrases[:3] if personality.catchphrases else [],
        )

        agent_ctx = AgentDialogueContext(
            npc_personality=agent_personality,
            current_mood=NPCMood.NEUTRAL,
            player_name=ctx.player_name,
            player_race="human",  # Would come from entity data
            player_class=None,
            player_reputation=ctx.relationship_level,
            topic=ctx.topic,
            player_message=ctx.player_input,
            conversation_history=ctx.conversation_history[-5:] if ctx.conversation_history else [],
            time_of_day="afternoon",
            location_name=ctx.location or "an unknown place",
            is_first_meeting=len(ctx.conversation_history) == 0,
        )

        self._stats["agent_calls"] += 1
        try:
            result = await self._dialogue_agent.run(
                "Generate an in-character response to the player.",
                deps=agent_ctx,
            )
            return result
        except Exception as e:
            logger.error(f"Dialogue agent error: {e}")
            self._stats["errors"] += 1
            # Return a minimal fallback
            return DialogueResponse(
                spoken_text=f"{ctx.npc_name} nods silently.",
            )

    # =========================================================================
    # Background Refill
    # =========================================================================

    async def _refill_loop(self) -> None:
        """Background loop to refill buffers."""
        while self._running:
            try:
                await self._refill_buffers()
            except Exception as e:
                logger.error(f"Buffer refill error: {e}")

            await asyncio.sleep(30)  # Check every 30 seconds

    async def _refill_buffers(self) -> None:
        """Refill any buffers below low watermark."""
        for category, buffer in self._buffers.items():
            if buffer.needs_refill:
                count = buffer.refill_count
                logger.debug(f"Refilling {category.value}: {count} items")

                for _ in range(count):
                    if not self._running:
                        break

                    prompt = self._build_narration_prompt(category, {})
                    try:
                        text = await self._generate_text(prompt)
                        await buffer.add(text)
                    except Exception as e:
                        logger.warning(f"Buffer refill generation failed: {e}")
                        break

    # =========================================================================
    # Statistics
    # =========================================================================

    async def get_stats(self) -> Dict[str, Any]:
        """Get DM statistics."""
        buffer_stats = {}
        for category, buffer in self._buffers.items():
            buffer_stats[category.value] = {
                "size": buffer.current_size,
                "needs_refill": buffer.needs_refill,
            }

        return {
            **self._stats,
            "cache_size": len(self._cache),
            "personality_count": len(self._personalities),
            "buffers": buffer_stats,
        }


# =============================================================================
# Actor Lifecycle
# =============================================================================

DM_ACTOR_NAME = "dungeon_master"
DM_NAMESPACE = "llmmud"


def start_dungeon_master(provider_config: Dict[str, Any]) -> ray.actor.ActorHandle:
    """Start the DungeonMaster actor."""
    actor = DungeonMaster.options(
        name=DM_ACTOR_NAME,
        namespace=DM_NAMESPACE,
        lifetime="detached",
    ).remote(provider_config)
    logger.info(f"Started DungeonMaster as {DM_NAMESPACE}/{DM_ACTOR_NAME}")
    return actor


def get_dungeon_master() -> ray.actor.ActorHandle:
    """Get the DungeonMaster actor."""
    return ray.get_actor(DM_ACTOR_NAME, namespace=DM_NAMESPACE)


def dungeon_master_exists() -> bool:
    """Check if the DungeonMaster exists."""
    try:
        ray.get_actor(DM_ACTOR_NAME, namespace=DM_NAMESPACE)
        return True
    except ValueError:
        return False
