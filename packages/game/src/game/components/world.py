"""
World State Components

Define global world state: time, weather, seasons, events.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Set

from core import ComponentData


class TimeOfDay(str, Enum):
    """Time periods within a game day."""

    DAWN = "dawn"  # 5-7
    MORNING = "morning"  # 7-12
    NOON = "noon"  # 12-13
    AFTERNOON = "afternoon"  # 13-17
    DUSK = "dusk"  # 17-19
    EVENING = "evening"  # 19-22
    NIGHT = "night"  # 22-5

    @property
    def is_dark(self) -> bool:
        """Check if this time is considered dark."""
        return self in [TimeOfDay.NIGHT, TimeOfDay.DUSK, TimeOfDay.DAWN]

    @property
    def light_level(self) -> int:
        """Light level from 0 (dark) to 100 (bright)."""
        levels = {
            TimeOfDay.DAWN: 40,
            TimeOfDay.MORNING: 80,
            TimeOfDay.NOON: 100,
            TimeOfDay.AFTERNOON: 90,
            TimeOfDay.DUSK: 50,
            TimeOfDay.EVENING: 30,
            TimeOfDay.NIGHT: 10,
        }
        return levels.get(self, 50)

    @property
    def description(self) -> str:
        """Time of day description."""
        descriptions = {
            TimeOfDay.DAWN: "The first light of dawn colors the sky.",
            TimeOfDay.MORNING: "The morning sun shines brightly.",
            TimeOfDay.NOON: "The sun is high overhead.",
            TimeOfDay.AFTERNOON: "The afternoon sun casts long shadows.",
            TimeOfDay.DUSK: "The sun sets on the horizon.",
            TimeOfDay.EVENING: "Stars begin to appear in the darkening sky.",
            TimeOfDay.NIGHT: "Night has fallen. Stars fill the sky.",
        }
        return descriptions.get(self, "")


class Season(str, Enum):
    """Seasons of the year."""

    SPRING = "spring"
    SUMMER = "summer"
    AUTUMN = "autumn"
    WINTER = "winter"

    @property
    def temperature_modifier(self) -> int:
        """Temperature modifier in Celsius."""
        mods = {
            Season.SPRING: 0,
            Season.SUMMER: 15,
            Season.AUTUMN: -5,
            Season.WINTER: -20,
        }
        return mods.get(self, 0)

    @property
    def day_length_modifier(self) -> float:
        """How much longer/shorter days are (multiplier)."""
        mods = {
            Season.SPRING: 1.0,
            Season.SUMMER: 1.3,
            Season.AUTUMN: 0.9,
            Season.WINTER: 0.7,
        }
        return mods.get(self, 1.0)

    @property
    def description(self) -> str:
        """Season description."""
        descriptions = {
            Season.SPRING: "Spring has arrived. New life blooms everywhere.",
            Season.SUMMER: "Summer's warmth fills the land.",
            Season.AUTUMN: "Autumn leaves drift in the cool breeze.",
            Season.WINTER: "Winter's chill grips the land.",
        }
        return descriptions.get(self, "")


class MoonPhase(str, Enum):
    """Moon phases."""

    NEW = "new"
    WAXING_CRESCENT = "waxing_crescent"
    FIRST_QUARTER = "first_quarter"
    WAXING_GIBBOUS = "waxing_gibbous"
    FULL = "full"
    WANING_GIBBOUS = "waning_gibbous"
    LAST_QUARTER = "last_quarter"
    WANING_CRESCENT = "waning_crescent"

    @property
    def night_light_bonus(self) -> int:
        """Bonus light at night from moon."""
        bonuses = {
            MoonPhase.NEW: 0,
            MoonPhase.WAXING_CRESCENT: 5,
            MoonPhase.FIRST_QUARTER: 15,
            MoonPhase.WAXING_GIBBOUS: 25,
            MoonPhase.FULL: 40,
            MoonPhase.WANING_GIBBOUS: 25,
            MoonPhase.LAST_QUARTER: 15,
            MoonPhase.WANING_CRESCENT: 5,
        }
        return bonuses.get(self, 0)

    @property
    def description(self) -> str:
        """Moon phase description."""
        descriptions = {
            MoonPhase.NEW: "The sky is dark; the moon is new.",
            MoonPhase.WAXING_CRESCENT: "A thin crescent moon hangs in the sky.",
            MoonPhase.FIRST_QUARTER: "A half moon lights the night.",
            MoonPhase.WAXING_GIBBOUS: "The moon is nearly full.",
            MoonPhase.FULL: "The full moon bathes the land in silver light.",
            MoonPhase.WANING_GIBBOUS: "The moon begins to wane.",
            MoonPhase.LAST_QUARTER: "A half moon rises late.",
            MoonPhase.WANING_CRESCENT: "A thin crescent moon fades toward dawn.",
        }
        return descriptions.get(self, "")


class WorldEventType(str, Enum):
    """Types of world events."""

    DOUBLE_EXP = "double_exp"
    DOUBLE_GOLD = "double_gold"
    INVASION = "invasion"
    FESTIVAL = "festival"
    ECLIPSE = "eclipse"
    BLOOD_MOON = "blood_moon"
    BOSS_SPAWN = "boss_spawn"
    WEATHER_EXTREME = "weather_extreme"


@dataclass
class WorldEvent:
    """An active world event."""

    event_id: str
    event_type: WorldEventType
    name: str
    description: str
    started_at: datetime
    ends_at: datetime
    affected_zones: Set[str] = field(default_factory=set)  # Empty = all zones
    multipliers: Dict[str, float] = field(default_factory=dict)  # exp: 2.0, gold: 1.5
    is_announced: bool = False

    @property
    def is_active(self) -> bool:
        """Check if event is currently active."""
        now = datetime.utcnow()
        return self.started_at <= now <= self.ends_at

    @property
    def time_remaining(self) -> timedelta:
        """Time remaining for this event."""
        return max(timedelta(0), self.ends_at - datetime.utcnow())

    def affects_zone(self, zone_id: str) -> bool:
        """Check if event affects a specific zone."""
        return len(self.affected_zones) == 0 or zone_id in self.affected_zones


@dataclass
class GameTime:
    """Representation of in-game time."""

    # Game time (1 real hour = 1 game day by default)
    year: int = 1
    month: int = 1  # 1-12
    day: int = 1  # 1-30
    hour: int = 6  # 0-23
    minute: int = 0  # 0-59

    # Time scaling
    real_seconds_per_game_minute: float = 2.5  # 1 real hour = 24 game hours

    @property
    def time_of_day(self) -> TimeOfDay:
        """Get current time of day."""
        if 5 <= self.hour < 7:
            return TimeOfDay.DAWN
        elif 7 <= self.hour < 12:
            return TimeOfDay.MORNING
        elif 12 <= self.hour < 13:
            return TimeOfDay.NOON
        elif 13 <= self.hour < 17:
            return TimeOfDay.AFTERNOON
        elif 17 <= self.hour < 19:
            return TimeOfDay.DUSK
        elif 19 <= self.hour < 22:
            return TimeOfDay.EVENING
        else:
            return TimeOfDay.NIGHT

    @property
    def season(self) -> Season:
        """Get current season based on month."""
        if self.month in [3, 4, 5]:
            return Season.SPRING
        elif self.month in [6, 7, 8]:
            return Season.SUMMER
        elif self.month in [9, 10, 11]:
            return Season.AUTUMN
        else:
            return Season.WINTER

    @property
    def moon_phase(self) -> MoonPhase:
        """Get current moon phase (changes every ~3-4 days)."""
        # Simplified: 8 phases, 30 day month = ~3.75 days per phase
        phase_day = (self.day - 1) % 30
        phase_index = phase_day // 4
        phases = list(MoonPhase)
        return phases[min(phase_index, len(phases) - 1)]

    def advance(self, real_seconds: float) -> bool:
        """
        Advance game time by real seconds.

        Returns True if day changed.
        """
        game_minutes = real_seconds / self.real_seconds_per_game_minute
        self.minute += int(game_minutes)

        day_changed = False

        while self.minute >= 60:
            self.minute -= 60
            self.hour += 1

        while self.hour >= 24:
            self.hour -= 24
            self.day += 1
            day_changed = True

        while self.day > 30:
            self.day -= 30
            self.month += 1

        while self.month > 12:
            self.month -= 12
            self.year += 1

        return day_changed

    def format_time(self) -> str:
        """Format time as string."""
        period = "AM" if self.hour < 12 else "PM"
        display_hour = self.hour if self.hour <= 12 else self.hour - 12
        if display_hour == 0:
            display_hour = 12
        return f"{display_hour}:{self.minute:02d} {period}"

    def format_date(self) -> str:
        """Format date as string."""
        month_names = [
            "Deepwinter", "Claws", "Storms", "Flowers",
            "Mists", "Flamerule", "Highsun", "Leaffall",
            "Highharvestide", "Rotting", "Nightal", "Hammer"
        ]
        month_name = month_names[self.month - 1] if 1 <= self.month <= 12 else "Unknown"
        return f"Day {self.day} of {month_name}, Year {self.year}"

    def format_full(self) -> str:
        """Format full date and time."""
        return f"{self.format_time()}, {self.format_date()}"


@dataclass
class WorldStateData(ComponentData):
    """
    Global world state - time, weather, events.

    This is a singleton component applied to a special "world" entity.
    """

    # Time
    game_time: GameTime = field(default_factory=GameTime)
    last_update: datetime = field(default_factory=datetime.utcnow)

    # Active events
    active_events: List[WorldEvent] = field(default_factory=list)

    # Announcements
    pending_announcements: List[str] = field(default_factory=list)

    # Statistics
    total_players_online: int = 0
    peak_players_today: int = 0
    server_start_time: datetime = field(default_factory=datetime.utcnow)

    def update_time(self) -> Optional[str]:
        """
        Update game time based on real time passed.

        Returns announcement if time of day changed.
        """
        now = datetime.utcnow()
        elapsed = (now - self.last_update).total_seconds()
        self.last_update = now

        old_time_of_day = self.game_time.time_of_day
        day_changed = self.game_time.advance(elapsed)

        new_time_of_day = self.game_time.time_of_day
        if new_time_of_day != old_time_of_day:
            return new_time_of_day.description

        return None

    def add_event(self, event: WorldEvent) -> None:
        """Add a world event."""
        self.active_events.append(event)
        if not event.is_announced:
            self.pending_announcements.append(
                f"*** WORLD EVENT: {event.name} has begun! {event.description} ***"
            )
            event.is_announced = True

    def remove_expired_events(self) -> List[str]:
        """Remove expired events. Returns ending announcements."""
        announcements = []
        now = datetime.utcnow()

        active = []
        for event in self.active_events:
            if event.ends_at > now:
                active.append(event)
            else:
                announcements.append(f"*** WORLD EVENT: {event.name} has ended. ***")

        self.active_events = active
        return announcements

    def get_event_multiplier(self, multiplier_type: str, zone_id: str = "") -> float:
        """Get combined multiplier from all active events."""
        total = 1.0
        for event in self.active_events:
            if event.is_active and event.affects_zone(zone_id):
                total *= event.multipliers.get(multiplier_type, 1.0)
        return total

    def get_active_events_for_zone(self, zone_id: str) -> List[WorldEvent]:
        """Get all active events affecting a zone."""
        return [
            e for e in self.active_events
            if e.is_active and e.affects_zone(zone_id)
        ]

    def pop_announcements(self) -> List[str]:
        """Get and clear pending announcements."""
        announcements = self.pending_announcements
        self.pending_announcements = []
        return announcements


@dataclass
class ZoneStateData(ComponentData):
    """
    Per-zone state data.

    Applied to zone entities.
    """

    zone_id: str = ""
    zone_name: str = ""

    # Population
    player_count: int = 0
    mob_count: int = 0
    npc_count: int = 0

    # Status
    is_instanced: bool = False
    is_pvp: bool = False
    min_level: int = 0
    max_level: int = 0

    # Zone weather (overrides global if set)
    weather_override: bool = False
    temperature_modifier: int = 0

    # Respawn timers
    last_respawn_check: datetime = field(default_factory=datetime.utcnow)
    respawn_multiplier: float = 1.0

    # Events affecting this zone
    active_event_ids: Set[str] = field(default_factory=set)


@dataclass
class RoomVisibilityData(ComponentData):
    """
    Visibility conditions for a room.
    """

    # Base visibility
    base_light_level: int = 50  # 0-100
    is_outdoors: bool = True
    is_underground: bool = False

    # Modifiers
    always_dark: bool = False
    always_lit: bool = False
    requires_light_source: bool = False

    def get_effective_light(
        self,
        time_of_day: TimeOfDay,
        moon_phase: MoonPhase,
        has_light_source: bool = False,
    ) -> int:
        """Calculate effective light level."""
        if self.always_lit:
            return 100
        if self.always_dark and not has_light_source:
            return 0

        # Start with base
        light = self.base_light_level

        # Outdoor rooms affected by time
        if self.is_outdoors and not self.is_underground:
            light = time_of_day.light_level
            if time_of_day.is_dark:
                light += moon_phase.night_light_bonus

        # Underground/indoor rooms use base unless lit
        elif self.is_underground:
            if has_light_source:
                light = max(light, 60)
            else:
                light = min(light, 10)

        return min(100, max(0, light))

    def can_see(
        self,
        time_of_day: TimeOfDay,
        moon_phase: MoonPhase,
        has_light_source: bool = False,
        has_darkvision: bool = False,
    ) -> bool:
        """Check if a player can see in this room."""
        light = self.get_effective_light(time_of_day, moon_phase, has_light_source)

        if has_darkvision:
            return light >= 0  # Can always see unless magically dark
        return light >= 20  # Need at least dim light
