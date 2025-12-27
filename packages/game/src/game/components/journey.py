"""Journey, mount, weather, and supply components for long travel mechanics."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from core.component import ComponentData


class WeatherType(str, Enum):
    """Weather conditions affecting travel."""

    CLEAR = "clear"
    CLOUDY = "cloudy"
    RAIN = "rain"
    STORM = "storm"
    FOG = "fog"
    SNOW = "snow"
    BLIZZARD = "blizzard"
    SANDSTORM = "sandstorm"
    ASH_FALL = "ash_fall"
    MAGICAL_MIST = "magical_mist"

    @property
    def movement_multiplier(self) -> float:
        """Movement cost multiplier for this weather."""
        multipliers = {
            WeatherType.CLEAR: 1.0,
            WeatherType.CLOUDY: 1.0,
            WeatherType.RAIN: 1.2,
            WeatherType.STORM: 1.5,
            WeatherType.FOG: 1.3,
            WeatherType.SNOW: 1.4,
            WeatherType.BLIZZARD: 2.0,
            WeatherType.SANDSTORM: 1.8,
            WeatherType.ASH_FALL: 1.3,
            WeatherType.MAGICAL_MIST: 1.5,
        }
        return multipliers.get(self, 1.0)

    @property
    def visibility_penalty(self) -> int:
        """Visibility reduction (0-100, higher = worse)."""
        penalties = {
            WeatherType.CLEAR: 0,
            WeatherType.CLOUDY: 10,
            WeatherType.RAIN: 30,
            WeatherType.STORM: 50,
            WeatherType.FOG: 70,
            WeatherType.SNOW: 40,
            WeatherType.BLIZZARD: 80,
            WeatherType.SANDSTORM: 90,
            WeatherType.ASH_FALL: 50,
            WeatherType.MAGICAL_MIST: 60,
        }
        return penalties.get(self, 0)

    @property
    def description(self) -> str:
        """Human-readable weather description."""
        descriptions = {
            WeatherType.CLEAR: "The sky is clear.",
            WeatherType.CLOUDY: "Gray clouds fill the sky.",
            WeatherType.RAIN: "Rain falls steadily from above.",
            WeatherType.STORM: "A violent storm rages around you.",
            WeatherType.FOG: "Thick fog obscures your surroundings.",
            WeatherType.SNOW: "Snow drifts gently from the sky.",
            WeatherType.BLIZZARD: "A fierce blizzard howls around you.",
            WeatherType.SANDSTORM: "Stinging sand whips through the air.",
            WeatherType.ASH_FALL: "Gray ash drifts down like snow.",
            WeatherType.MAGICAL_MIST: "An unnatural mist swirls with faint lights.",
        }
        return descriptions.get(self, "The weather is unremarkable.")


class MountType(str, Enum):
    """Types of mounts available for travel."""

    HORSE = "horse"
    WAR_HORSE = "war_horse"
    PONY = "pony"
    CAMEL = "camel"
    GIANT_LIZARD = "giant_lizard"
    GRIFFIN = "griffin"
    NIGHTMARE = "nightmare"
    GIANT_SPIDER = "giant_spider"
    GOAT = "goat"
    BOAT = "boat"

    @property
    def speed_multiplier(self) -> float:
        """How much faster travel is with this mount."""
        speeds = {
            MountType.HORSE: 2.0,
            MountType.WAR_HORSE: 1.8,
            MountType.PONY: 1.5,
            MountType.CAMEL: 1.8,
            MountType.GIANT_LIZARD: 1.6,
            MountType.GRIFFIN: 3.0,
            MountType.NIGHTMARE: 2.5,
            MountType.GIANT_SPIDER: 1.4,
            MountType.GOAT: 1.3,
            MountType.BOAT: 2.0,
        }
        return speeds.get(self, 1.0)

    @property
    def stamina_cost(self) -> int:
        """Stamina cost per room traveled."""
        costs = {
            MountType.HORSE: 2,
            MountType.WAR_HORSE: 3,
            MountType.PONY: 1,
            MountType.CAMEL: 1,
            MountType.GIANT_LIZARD: 2,
            MountType.GRIFFIN: 4,
            MountType.NIGHTMARE: 3,
            MountType.GIANT_SPIDER: 2,
            MountType.GOAT: 1,
            MountType.BOAT: 0,
        }
        return costs.get(self, 1)

    @property
    def terrain_bonuses(self) -> Dict[str, float]:
        """Terrain types where this mount excels (multiplier bonus)."""
        bonuses: Dict[MountType, Dict[str, float]] = {
            MountType.HORSE: {"field": 1.2, "road": 1.3},
            MountType.WAR_HORSE: {"field": 1.1, "road": 1.2},
            MountType.PONY: {"mountain": 1.2, "hills": 1.2},
            MountType.CAMEL: {"desert": 1.5, "volcanic": 1.2},
            MountType.GIANT_LIZARD: {"swamp": 1.4, "underground": 1.2},
            MountType.GRIFFIN: {"mountain": 1.5, "sky": 2.0},
            MountType.NIGHTMARE: {"volcanic": 1.5, "underground": 1.3},
            MountType.GIANT_SPIDER: {"underground": 1.5, "forest": 1.2},
            MountType.GOAT: {"mountain": 1.5, "alpine": 1.4},
            MountType.BOAT: {"coastal": 2.0, "underwater": 1.5},
        }
        return bonuses.get(self, {})


class SupplyType(str, Enum):
    """Types of supplies consumed during travel."""

    FOOD = "food"
    WATER = "water"
    TORCH = "torch"
    ROPE = "rope"
    HEALING_SUPPLIES = "healing_supplies"
    MOUNT_FEED = "mount_feed"


@dataclass
class SupplyItem:
    """A consumable supply item."""

    supply_type: SupplyType
    quantity: int
    quality: int = 1  # 1-5, affects effectiveness


@dataclass
class MountData(ComponentData):
    """Data for a player's mount."""

    mount_type: MountType
    name: str
    max_stamina: int = 100
    current_stamina: int = 100
    loyalty: int = 50  # 0-100, affects behavior
    is_mounted: bool = False
    fed_today: bool = False
    training_level: int = 1  # 1-5, improves stats

    @property
    def effective_speed(self) -> float:
        """Speed multiplier including training bonus."""
        base = self.mount_type.speed_multiplier
        training_bonus = 1.0 + (self.training_level - 1) * 0.1
        stamina_factor = max(0.5, self.current_stamina / self.max_stamina)
        return base * training_bonus * stamina_factor

    def consume_stamina(self, amount: int) -> bool:
        """Consume mount stamina. Returns False if exhausted."""
        cost = self.mount_type.stamina_cost * amount
        if self.current_stamina >= cost:
            self.current_stamina -= cost
            return True
        return False

    def rest(self, hours: int = 1) -> None:
        """Restore mount stamina through rest."""
        recovery = hours * 10 * (2 if self.fed_today else 1)
        self.current_stamina = min(self.max_stamina, self.current_stamina + recovery)


@dataclass
class SupplyData(ComponentData):
    """Tracks a player's travel supplies."""

    supplies: Dict[SupplyType, SupplyItem] = field(default_factory=dict)
    consumption_rate: float = 1.0  # Multiplier for supply usage

    def add_supply(self, supply_type: SupplyType, quantity: int, quality: int = 1) -> None:
        """Add supplies to inventory."""
        if supply_type in self.supplies:
            existing = self.supplies[supply_type]
            # Average quality when combining
            total_qty = existing.quantity + quantity
            avg_quality = (
                (existing.quality * existing.quantity) + (quality * quantity)
            ) // total_qty
            self.supplies[supply_type] = SupplyItem(supply_type, total_qty, avg_quality)
        else:
            self.supplies[supply_type] = SupplyItem(supply_type, quantity, quality)

    def consume_supply(self, supply_type: SupplyType, amount: int = 1) -> bool:
        """Consume supplies. Returns False if insufficient."""
        if supply_type not in self.supplies:
            return False
        supply = self.supplies[supply_type]
        actual_amount = int(amount * self.consumption_rate)
        if supply.quantity >= actual_amount:
            supply.quantity -= actual_amount
            if supply.quantity <= 0:
                del self.supplies[supply_type]
            return True
        return False

    def get_quantity(self, supply_type: SupplyType) -> int:
        """Get current quantity of a supply type."""
        if supply_type in self.supplies:
            return self.supplies[supply_type].quantity
        return 0

    def has_sufficient(self, supply_type: SupplyType, amount: int) -> bool:
        """Check if sufficient supplies are available."""
        return self.get_quantity(supply_type) >= int(amount * self.consumption_rate)


@dataclass
class WeatherData(ComponentData):
    """Current weather state for a region or zone."""

    weather_type: WeatherType = WeatherType.CLEAR
    intensity: float = 1.0  # 0.0-2.0, affects severity
    duration_remaining: int = 60  # Minutes until weather changes
    wind_direction: str = "north"
    wind_strength: int = 0  # 0-100
    temperature_modifier: int = 0  # Degrees from normal (-30 to +30)
    magical: bool = False  # Is this weather supernatural?

    @property
    def effective_movement_multiplier(self) -> float:
        """Movement cost including intensity."""
        base = self.weather_type.movement_multiplier
        # Intensity scales the penalty portion
        penalty = (base - 1.0) * self.intensity
        return 1.0 + penalty

    @property
    def effective_visibility_penalty(self) -> int:
        """Visibility penalty including intensity."""
        base = self.weather_type.visibility_penalty
        return int(base * self.intensity)

    def get_description(self) -> str:
        """Get weather description with intensity modifiers."""
        base_desc = self.weather_type.description
        if self.intensity < 0.5:
            return f"Light conditions: {base_desc.lower()}"
        elif self.intensity > 1.5:
            return f"Severe conditions: {base_desc}"
        return base_desc


@dataclass
class WaypointVisit:
    """Record of visiting a waypoint."""

    waypoint_name: str
    visited_at: datetime
    rested_here: bool = False
    supplies_restocked: bool = False


@dataclass
class JourneyData(ComponentData):
    """Tracks long journeys through dynamic regions."""

    # Current journey state
    current_region: str = ""
    is_active: bool = False
    started_at: Optional[datetime] = None

    # Progress tracking
    distance_traveled: int = 0  # Rooms traversed
    total_distance: int = 0  # Expected rooms to exit
    current_leg: int = 0  # Which segment of the journey (between waypoints)

    # Waypoint tracking
    waypoints_discovered: List[str] = field(default_factory=list)
    waypoints_visited: List[WaypointVisit] = field(default_factory=list)
    next_waypoint: Optional[str] = None

    # Journey statistics
    rest_count: int = 0  # Times rested during journey
    encounters_faced: int = 0  # Combat encounters
    encounters_fled: int = 0  # Encounters avoided
    supplies_consumed: int = 0  # Total supply units used
    rooms_generated: int = 0  # New rooms generated during journey

    # Survival state
    fatigue: int = 0  # 0-100, affects combat/movement
    morale: int = 100  # 0-100, affects random events
    last_rest: Optional[datetime] = None
    last_meal: Optional[datetime] = None
    last_drink: Optional[datetime] = None

    # Shortcuts discovered
    shortcuts_found: List[str] = field(default_factory=list)

    def start_journey(self, region_id: str, estimated_distance: int) -> None:
        """Begin a new journey through a region."""
        self.current_region = region_id
        self.is_active = True
        self.started_at = datetime.utcnow()
        self.distance_traveled = 0
        self.total_distance = estimated_distance
        self.current_leg = 0
        self.fatigue = 0
        self.morale = 100

    def end_journey(self) -> Dict:
        """Complete the journey and return summary statistics."""
        summary = {
            "region": self.current_region,
            "duration": (datetime.utcnow() - self.started_at).total_seconds() / 60
            if self.started_at
            else 0,
            "distance": self.distance_traveled,
            "waypoints_visited": len(self.waypoints_visited),
            "encounters": self.encounters_faced,
            "encounters_fled": self.encounters_fled,
            "rest_stops": self.rest_count,
            "supplies_used": self.supplies_consumed,
            "shortcuts_found": len(self.shortcuts_found),
        }
        self.is_active = False
        self.current_region = ""
        return summary

    def advance(self, rooms: int = 1) -> None:
        """Record progress through the region."""
        self.distance_traveled += rooms
        self.fatigue = min(100, self.fatigue + rooms)

    def record_rest(self, waypoint_name: Optional[str] = None) -> None:
        """Record a rest stop."""
        self.rest_count += 1
        self.last_rest = datetime.utcnow()
        self.fatigue = max(0, self.fatigue - 30)
        self.morale = min(100, self.morale + 10)

        if waypoint_name and waypoint_name not in [w.waypoint_name for w in self.waypoints_visited]:
            self.waypoints_visited.append(
                WaypointVisit(
                    waypoint_name=waypoint_name,
                    visited_at=datetime.utcnow(),
                    rested_here=True,
                )
            )

    def record_encounter(self, fled: bool = False) -> None:
        """Record a combat encounter."""
        self.encounters_faced += 1
        if fled:
            self.encounters_fled += 1
            self.morale = max(0, self.morale - 5)
        else:
            self.morale = min(100, self.morale + 2)

    def consume_supplies(self, amount: int = 1) -> None:
        """Record supply consumption."""
        self.supplies_consumed += amount

    def discover_waypoint(self, waypoint_name: str) -> bool:
        """Discover a new waypoint. Returns True if newly discovered."""
        if waypoint_name not in self.waypoints_discovered:
            self.waypoints_discovered.append(waypoint_name)
            self.morale = min(100, self.morale + 5)
            return True
        return False

    def discover_shortcut(self, shortcut_id: str) -> bool:
        """Discover a shortcut. Returns True if newly discovered."""
        if shortcut_id not in self.shortcuts_found:
            self.shortcuts_found.append(shortcut_id)
            return True
        return False

    @property
    def progress_percentage(self) -> float:
        """Journey completion percentage."""
        if self.total_distance <= 0:
            return 0.0
        return min(100.0, (self.distance_traveled / self.total_distance) * 100)

    @property
    def is_fatigued(self) -> bool:
        """Check if traveler is suffering from fatigue."""
        return self.fatigue >= 70

    @property
    def is_exhausted(self) -> bool:
        """Check if traveler is exhausted (severe penalties)."""
        return self.fatigue >= 90

    @property
    def fatigue_movement_penalty(self) -> float:
        """Movement speed penalty from fatigue (1.0 = no penalty)."""
        if self.fatigue < 50:
            return 1.0
        elif self.fatigue < 70:
            return 1.2
        elif self.fatigue < 90:
            return 1.5
        else:
            return 2.0

    def needs_food(self, hours_threshold: int = 8) -> bool:
        """Check if traveler needs food."""
        if self.last_meal is None:
            return True
        hours_since = (datetime.utcnow() - self.last_meal).total_seconds() / 3600
        return hours_since >= hours_threshold

    def needs_water(self, hours_threshold: int = 4) -> bool:
        """Check if traveler needs water."""
        if self.last_drink is None:
            return True
        hours_since = (datetime.utcnow() - self.last_drink).total_seconds() / 3600
        return hours_since >= hours_threshold

    def eat(self) -> None:
        """Record eating."""
        self.last_meal = datetime.utcnow()
        self.fatigue = max(0, self.fatigue - 5)

    def drink(self) -> None:
        """Record drinking."""
        self.last_drink = datetime.utcnow()
        self.fatigue = max(0, self.fatigue - 3)


@dataclass
class RegionWeatherData(ComponentData):
    """Weather patterns for a dynamic region."""

    region_id: str
    current_weather: WeatherData = field(default_factory=WeatherData)
    allowed_weather_types: List[WeatherType] = field(
        default_factory=lambda: [WeatherType.CLEAR, WeatherType.CLOUDY, WeatherType.RAIN]
    )
    weather_change_chance: float = 0.1  # Chance per tick to change weather
    base_temperature: int = 20  # Celsius
    has_day_night: bool = True
    is_underground: bool = False  # Underground areas have no weather

    def get_random_weather(self) -> WeatherType:
        """Get a random weather type appropriate for this region."""
        import random

        if self.is_underground:
            return WeatherType.CLEAR  # No weather underground
        return random.choice(self.allowed_weather_types)

    def should_change_weather(self) -> bool:
        """Check if weather should change this tick."""
        import random

        if self.is_underground:
            return False
        return random.random() < self.weather_change_chance
