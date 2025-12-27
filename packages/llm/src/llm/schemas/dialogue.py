"""
Dialogue Generation Schemas

Pydantic models for LLM-generated NPC dialogue.
"""

from enum import Enum
from typing import List, Optional, Literal

from pydantic import BaseModel, Field


class NPCMood(str, Enum):
    """Current mood of the NPC."""

    FRIENDLY = "friendly"
    NEUTRAL = "neutral"
    SUSPICIOUS = "suspicious"
    HOSTILE = "hostile"
    FEARFUL = "fearful"
    EXCITED = "excited"
    BORED = "bored"
    BUSY = "busy"


class SpeechStyle(str, Enum):
    """How the NPC speaks."""

    FORMAL = "formal"  # Educated, proper
    CASUAL = "casual"  # Relaxed, informal
    ARCHAIC = "archaic"  # Old-fashioned, "thee" and "thou"
    GRUFF = "gruff"  # Short, curt
    VERBOSE = "verbose"  # Long-winded, detailed
    CRYPTIC = "cryptic"  # Mysterious, hints
    SIMPLE = "simple"  # Few words, basic vocabulary


class DialogueResponse(BaseModel):
    """Schema for NPC dialogue response."""

    spoken_text: str = Field(
        ...,
        min_length=5,
        max_length=300,
        description="What the NPC says (dialogue only)",
    )
    emote: Optional[str] = Field(
        default=None,
        max_length=80,
        description="Physical action/expression accompanying speech",
    )
    mood_change: Optional[Literal["friendlier", "hostile", "neutral"]] = Field(
        default=None,
        description="How interaction affects NPC's mood",
    )
    reveals_information: bool = Field(
        default=False,
        description="Whether NPC shares useful information",
    )
    information_topic: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Topic of revealed information",
    )
    offers_quest: bool = Field(
        default=False,
        description="Whether NPC offers a quest",
    )
    offers_trade: bool = Field(
        default=False,
        description="Whether NPC offers to trade",
    )
    ends_conversation: bool = Field(
        default=False,
        description="Whether NPC ends the conversation",
    )


class NPCPersonality(BaseModel):
    """Personality traits for consistent NPC behavior."""

    name: str = Field(..., description="NPC's name")
    role: str = Field(..., description="NPC's role/occupation")
    speech_style: SpeechStyle = Field(..., description="How they speak")
    default_mood: NPCMood = Field(
        default=NPCMood.NEUTRAL, description="Typical mood"
    )
    background: str = Field(
        ..., max_length=200, description="Brief character background"
    )
    motivation: str = Field(
        ..., max_length=100, description="What drives this NPC"
    )
    quirks: List[str] = Field(
        default_factory=list,
        max_length=3,
        description="Distinctive mannerisms",
    )
    knowledge_topics: List[str] = Field(
        default_factory=list,
        max_length=5,
        description="Topics they can discuss",
    )
    catchphrases: List[str] = Field(
        default_factory=list,
        max_length=3,
        description="Distinctive phrases they use",
    )
    likes: List[str] = Field(
        default_factory=list,
        max_length=3,
        description="Things that please them",
    )
    dislikes: List[str] = Field(
        default_factory=list,
        max_length=3,
        description="Things that annoy them",
    )


class DialogueContext(BaseModel):
    """Context provided to LLM for dialogue generation."""

    npc_personality: NPCPersonality = Field(
        ..., description="Personality of the speaking NPC"
    )
    current_mood: NPCMood = Field(
        default=NPCMood.NEUTRAL, description="NPC's current mood"
    )
    player_name: str = Field(..., description="Name of the player")
    player_race: str = Field(..., description="Race of the player")
    player_class: Optional[str] = Field(
        default=None, description="Class of the player"
    )
    player_reputation: int = Field(
        default=0,
        ge=-100,
        le=100,
        description="Player's reputation with NPC's faction",
    )
    topic: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Specific topic being discussed",
    )
    player_message: str = Field(
        ...,
        max_length=200,
        description="What the player said/asked",
    )
    conversation_history: List[str] = Field(
        default_factory=list,
        max_length=10,
        description="Recent dialogue for context",
    )
    time_of_day: Literal["morning", "afternoon", "evening", "night"] = Field(
        default="afternoon", description="Current time of day"
    )
    location_name: str = Field(
        ..., description="Where the conversation takes place"
    )
    is_first_meeting: bool = Field(
        default=True, description="Whether player has met NPC before"
    )
    available_quests: List[str] = Field(
        default_factory=list,
        description="Quests NPC can offer",
    )
    available_topics: List[str] = Field(
        default_factory=list,
        description="Topics NPC knows about",
    )


class GreetingResponse(BaseModel):
    """Schema for NPC greeting when player first interacts."""

    greeting: str = Field(
        ...,
        max_length=150,
        description="Initial greeting based on reputation/time",
    )
    emote: Optional[str] = Field(
        default=None,
        max_length=60,
        description="Physical action with greeting",
    )
    recognizes_player: bool = Field(
        default=False,
        description="Whether NPC remembers the player",
    )
    recognition_text: Optional[str] = Field(
        default=None,
        max_length=80,
        description="What NPC says if they recognize player",
    )
