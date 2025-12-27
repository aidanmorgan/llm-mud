"""Journey, mount, weather, and supply systems for long travel mechanics."""

import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

from core.system import System

from ..components.journey import (
    JourneyData,
    MountData,
    RegionWeatherData,
    SupplyData,
    SupplyType,
    WeatherData,
    WeatherType,
)
from ..components.spatial import LocationData, SectorType


class JourneyTrackingSystem(System):
    """Tracks player journeys through dynamic regions and applies fatigue/morale effects."""

    priority = 95  # Run early, before movement effects

    required_components = ["JourneyData", "LocationData"]

    async def process(self, entity_id: str, components: Dict) -> None:
        """Process journey state for an entity."""
        journey: JourneyData = components["JourneyData"]
        location: LocationData = components["LocationData"]

        if not journey.is_active:
            return

        # Check for fatigue effects
        if journey.is_exhausted:
            # Apply exhaustion debuff - this could trigger a status effect
            await self._apply_exhaustion_effect(entity_id)
        elif journey.is_fatigued:
            await self._apply_fatigue_effect(entity_id)

        # Check hunger/thirst
        if journey.needs_food(hours_threshold=8):
            await self._apply_hunger_effect(entity_id, journey)
        if journey.needs_water(hours_threshold=4):
            await self._apply_thirst_effect(entity_id, journey)

    async def _apply_exhaustion_effect(self, entity_id: str) -> None:
        """Apply severe exhaustion penalties."""
        # Could add a status effect component here
        pass

    async def _apply_fatigue_effect(self, entity_id: str) -> None:
        """Apply moderate fatigue penalties."""
        pass

    async def _apply_hunger_effect(self, entity_id: str, journey: JourneyData) -> None:
        """Apply hunger penalties."""
        journey.morale = max(0, journey.morale - 1)

    async def _apply_thirst_effect(self, entity_id: str, journey: JourneyData) -> None:
        """Apply thirst penalties (more severe than hunger)."""
        journey.morale = max(0, journey.morale - 2)
        journey.fatigue = min(100, journey.fatigue + 1)


class SupplyConsumptionSystem(System):
    """Automatically consumes supplies during travel and rest."""

    priority = 96  # Run after journey tracking

    required_components = ["SupplyData", "JourneyData"]

    # Time intervals for automatic consumption (in game ticks)
    FOOD_INTERVAL_TICKS = 480  # ~8 hours at 1 tick/minute
    WATER_INTERVAL_TICKS = 240  # ~4 hours
    TORCH_INTERVAL_TICKS = 60  # 1 hour for underground

    def __init__(self):
        super().__init__()
        self._last_consumption: Dict[str, Dict[SupplyType, int]] = {}

    async def process(self, entity_id: str, components: Dict) -> None:
        """Process supply consumption for an entity."""
        supplies: SupplyData = components["SupplyData"]
        journey: JourneyData = components["JourneyData"]

        if not journey.is_active:
            return

        current_tick = self._get_current_tick()

        # Initialize tracking for this entity
        if entity_id not in self._last_consumption:
            self._last_consumption[entity_id] = {}

        # Check food consumption
        await self._maybe_consume(
            entity_id,
            supplies,
            journey,
            SupplyType.FOOD,
            self.FOOD_INTERVAL_TICKS,
            current_tick,
            on_consume=journey.eat,
            on_depleted=lambda: self._notify_out_of_supplies(entity_id, "food"),
        )

        # Check water consumption
        await self._maybe_consume(
            entity_id,
            supplies,
            journey,
            SupplyType.WATER,
            self.WATER_INTERVAL_TICKS,
            current_tick,
            on_consume=journey.drink,
            on_depleted=lambda: self._notify_out_of_supplies(entity_id, "water"),
        )

    async def _maybe_consume(
        self,
        entity_id: str,
        supplies: SupplyData,
        journey: JourneyData,
        supply_type: SupplyType,
        interval: int,
        current_tick: int,
        on_consume=None,
        on_depleted=None,
    ) -> None:
        """Consume a supply if the interval has passed."""
        last = self._last_consumption[entity_id].get(supply_type, 0)

        if current_tick - last >= interval:
            if supplies.consume_supply(supply_type, 1):
                journey.consume_supplies(1)
                self._last_consumption[entity_id][supply_type] = current_tick
                if on_consume:
                    on_consume()
            else:
                if on_depleted:
                    on_depleted()

    def _get_current_tick(self) -> int:
        """Get current game tick (simplified - uses seconds since epoch)."""
        return int(datetime.utcnow().timestamp())

    def _notify_out_of_supplies(self, entity_id: str, supply_name: str) -> None:
        """Notify player they're out of a supply type."""
        # This would send a message to the player
        pass


class MountStaminaSystem(System):
    """Manages mount stamina recovery and feeding."""

    priority = 97

    required_components = ["MountData"]

    # Ticks between stamina recovery
    RECOVERY_INTERVAL = 60  # 1 minute

    def __init__(self):
        super().__init__()
        self._last_recovery: Dict[str, int] = {}

    async def process(self, entity_id: str, components: Dict) -> None:
        """Process mount stamina recovery."""
        mount: MountData = components["MountData"]

        current_tick = int(datetime.utcnow().timestamp())
        last = self._last_recovery.get(entity_id, 0)

        if current_tick - last >= self.RECOVERY_INTERVAL:
            # Recover stamina when not mounted
            if not mount.is_mounted:
                recovery = 5 if mount.fed_today else 2
                mount.current_stamina = min(mount.max_stamina, mount.current_stamina + recovery)

            # Reset fed status at "midnight" (simplified)
            hour = datetime.utcnow().hour
            if hour == 0:
                mount.fed_today = False

            self._last_recovery[entity_id] = current_tick


class WeatherSystem(System):
    """Updates weather conditions in regions."""

    priority = 10  # Run early

    required_components = ["RegionWeatherData"]

    def __init__(self):
        super().__init__()
        self._weather_messages: Dict[WeatherType, List[str]] = {
            WeatherType.CLEAR: [
                "A pleasant breeze rustles past.",
                "Sunlight filters through the area.",
            ],
            WeatherType.CLOUDY: [
                "Gray clouds drift overhead.",
                "The sky darkens briefly as clouds pass.",
            ],
            WeatherType.RAIN: [
                "Rain patters steadily around you.",
                "Water drips from every surface.",
                "The rain intensifies for a moment.",
            ],
            WeatherType.STORM: [
                "Lightning flashes in the distance!",
                "Thunder rolls across the sky.",
                "The wind howls fiercely.",
                "A gust of wind nearly knocks you off balance.",
            ],
            WeatherType.FOG: [
                "The fog swirls around you.",
                "Shapes seem to move in the mist.",
                "Visibility drops as the fog thickens.",
            ],
            WeatherType.SNOW: [
                "Snowflakes drift lazily downward.",
                "A thin layer of snow covers everything.",
                "Your breath mists in the cold air.",
            ],
            WeatherType.BLIZZARD: [
                "The blizzard howls around you!",
                "Snow blinds you momentarily.",
                "The wind cuts through your clothing.",
                "You can barely see your hand in front of your face.",
            ],
            WeatherType.SANDSTORM: [
                "Sand stings your exposed skin.",
                "The wind whips sand into your eyes.",
                "A wall of sand approaches!",
            ],
            WeatherType.ASH_FALL: [
                "Gray ash drifts down like snow.",
                "The air tastes of sulfur and ash.",
                "Ash crunches underfoot.",
            ],
            WeatherType.MAGICAL_MIST: [
                "Strange lights flicker in the mist.",
                "The mist seems to whisper secrets.",
                "Reality feels uncertain in this fog.",
            ],
        }

    async def process(self, entity_id: str, components: Dict) -> None:
        """Process weather updates for a region."""
        region_weather: RegionWeatherData = components["RegionWeatherData"]

        # Decrement duration
        if region_weather.current_weather.duration_remaining > 0:
            region_weather.current_weather.duration_remaining -= 1

        # Check for weather change
        if (
            region_weather.current_weather.duration_remaining <= 0
            or region_weather.should_change_weather()
        ):
            await self._change_weather(region_weather)

    async def _change_weather(self, region_weather: RegionWeatherData) -> None:
        """Change the weather in a region."""
        new_type = region_weather.get_random_weather()
        old_type = region_weather.current_weather.weather_type

        # Create new weather data
        region_weather.current_weather = WeatherData(
            weather_type=new_type,
            intensity=random.uniform(0.5, 1.5),
            duration_remaining=random.randint(30, 180),
            wind_direction=random.choice(["north", "south", "east", "west"]),
            wind_strength=random.randint(0, 100),
            temperature_modifier=random.randint(-10, 10) + region_weather.base_temperature,
            magical=new_type == WeatherType.MAGICAL_MIST,
        )

        # Broadcast weather change to players in region
        if new_type != old_type:
            await self._broadcast_weather_change(region_weather.region_id, old_type, new_type)

    async def _broadcast_weather_change(
        self, region_id: str, old_type: WeatherType, new_type: WeatherType
    ) -> None:
        """Broadcast weather change to all players in region."""
        # This would use the event system to notify players
        pass

    def get_weather_ambient_message(self, weather_type: WeatherType) -> Optional[str]:
        """Get a random ambient message for the current weather."""
        messages = self._weather_messages.get(weather_type, [])
        if messages:
            return random.choice(messages)
        return None


class WaypointDiscoverySystem(System):
    """Handles waypoint discovery and rest stop functionality."""

    priority = 94

    required_components = ["JourneyData", "LocationData"]

    # Known waypoints by region (would be loaded from YAML in production)
    _waypoints_by_region: Dict[str, Dict[str, Dict]] = {}

    @classmethod
    def register_waypoint(
        cls, region_id: str, waypoint_name: str, coordinate: tuple, is_required: bool = False
    ) -> None:
        """Register a waypoint for a region."""
        if region_id not in cls._waypoints_by_region:
            cls._waypoints_by_region[region_id] = {}
        cls._waypoints_by_region[region_id][waypoint_name] = {
            "coordinate": coordinate,
            "is_required": is_required,
        }

    async def process(self, entity_id: str, components: Dict) -> None:
        """Check if player has discovered a waypoint."""
        journey: JourneyData = components["JourneyData"]
        location: LocationData = components["LocationData"]

        if not journey.is_active:
            return

        region_id = journey.current_region
        if region_id not in self._waypoints_by_region:
            return

        # Check each waypoint in the region
        for waypoint_name, waypoint_data in self._waypoints_by_region[region_id].items():
            # In a real implementation, we'd check if the player's current
            # room coordinate matches the waypoint coordinate
            # For now, this is a placeholder
            pass


class MovementCostCalculator:
    """Utility class to calculate movement costs including weather, mounts, and fatigue."""

    @staticmethod
    def calculate_movement_cost(
        base_cost: float,
        sector_type: SectorType,
        weather: Optional[WeatherData] = None,
        mount: Optional[MountData] = None,
        journey: Optional[JourneyData] = None,
    ) -> float:
        """Calculate final movement cost considering all factors."""
        cost = base_cost * sector_type.movement_cost

        # Apply weather penalty
        if weather:
            cost *= weather.effective_movement_multiplier

        # Apply mount speed bonus
        if mount and mount.is_mounted and mount.current_stamina > 0:
            # Check terrain bonuses
            terrain_key = sector_type.value
            terrain_bonus = mount.mount_type.terrain_bonuses.get(terrain_key, 1.0)
            cost /= mount.effective_speed * terrain_bonus

        # Apply fatigue penalty
        if journey:
            cost *= journey.fatigue_movement_penalty

        return max(0.5, cost)  # Minimum cost of 0.5

    @staticmethod
    def calculate_travel_time(
        rooms: int,
        sector_type: SectorType,
        weather: Optional[WeatherData] = None,
        mount: Optional[MountData] = None,
    ) -> int:
        """Calculate travel time in minutes for a journey segment."""
        base_time = rooms * 5  # 5 minutes per room base

        # Sector type modifier
        base_time *= sector_type.movement_cost

        # Weather modifier
        if weather:
            base_time *= weather.effective_movement_multiplier

        # Mount speed
        if mount and mount.is_mounted:
            base_time /= mount.effective_speed

        return int(base_time)


class JourneyEventGenerator:
    """Generates random events during long journeys."""

    def __init__(self):
        self._event_chances: Dict[str, float] = {
            "encounter": 0.15,  # Combat encounter
            "discovery": 0.10,  # Find something interesting
            "weather_change": 0.08,  # Weather shifts
            "shortcut": 0.05,  # Find a shortcut
            "rest_spot": 0.07,  # Find a good rest location
            "resource": 0.12,  # Find supplies
            "hazard": 0.08,  # Environmental hazard
        }

    def should_trigger_event(self, journey: JourneyData) -> Optional[str]:
        """Check if a random event should trigger."""
        # Lower morale increases negative event chances
        morale_modifier = (100 - journey.morale) / 200  # 0 to 0.5

        for event_type, base_chance in self._event_chances.items():
            # Modify chance based on morale
            if event_type in ["encounter", "hazard"]:
                chance = base_chance + morale_modifier
            elif event_type in ["discovery", "shortcut", "resource"]:
                chance = base_chance - morale_modifier / 2
            else:
                chance = base_chance

            if random.random() < chance:
                return event_type

        return None

    def generate_discovery_message(self, region_theme: str) -> str:
        """Generate a discovery message appropriate to the region."""
        discoveries = [
            "You notice an unusual rock formation.",
            "A faint trail branches off from the main path.",
            "You spot signs of previous travelers.",
            "Something glints in the distance.",
            "You discover a sheltered alcove.",
        ]
        return random.choice(discoveries)

    def generate_hazard_message(self, weather: Optional[WeatherData] = None) -> str:
        """Generate a hazard message."""
        hazards = [
            "The ground becomes treacherous underfoot.",
            "You nearly step into a hidden pit.",
            "Loose rocks tumble down nearby.",
            "The path narrows dangerously.",
        ]
        if weather and weather.weather_type in [WeatherType.STORM, WeatherType.BLIZZARD]:
            hazards.extend(
                [
                    "A flash flood surges across your path!",
                    "Lightning strikes dangerously close!",
                ]
            )
        return random.choice(hazards)
