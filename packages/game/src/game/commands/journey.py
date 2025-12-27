"""Journey, mount, weather, and supply commands."""

from typing import Optional

from ..commands.registry import command, CommandCategory


@command(
    name="journey",
    aliases=["trip", "travel"],
    category=CommandCategory.INFO,
    help_text="View your current journey status and progress.",
)
async def cmd_journey(player_id: str, args: str, game_state) -> str:
    """Display journey status including progress, fatigue, and supplies."""
    from ..components.journey import JourneyData, SupplyData, SupplyType

    journey = await game_state.get_component(player_id, "JourneyData")

    if not journey or not journey.is_active:
        return "You are not currently on a long journey through a dynamic region."

    lines = [
        f"=== Journey Through {journey.current_region.replace('_', ' ').title()} ===",
        "",
        f"Progress: {journey.distance_traveled}/{journey.total_distance} rooms ({journey.progress_percentage:.1f}%)",
        f"Current Leg: {journey.current_leg + 1}",
        "",
    ]

    # Status bars
    fatigue_bar = _make_bar(journey.fatigue, 100, 20, reverse=True)
    morale_bar = _make_bar(journey.morale, 100, 20)

    lines.extend([
        f"Fatigue:  [{fatigue_bar}] {journey.fatigue}%",
        f"Morale:   [{morale_bar}] {journey.morale}%",
        "",
    ])

    # Status effects
    if journey.is_exhausted:
        lines.append("*** You are EXHAUSTED! Movement and combat severely penalized. ***")
    elif journey.is_fatigued:
        lines.append("* You are fatigued. Consider resting soon. *")

    if journey.needs_food():
        lines.append("* You are hungry. You should eat something. *")
    if journey.needs_water():
        lines.append("* You are thirsty. You need water. *")

    # Waypoints
    if journey.waypoints_discovered:
        lines.append("")
        lines.append(f"Waypoints Discovered: {len(journey.waypoints_discovered)}")
        for wp in journey.waypoints_discovered[-3:]:  # Last 3
            lines.append(f"  - {wp}")

    if journey.next_waypoint:
        lines.append(f"Next Waypoint: {journey.next_waypoint}")

    # Statistics
    lines.extend([
        "",
        "--- Journey Statistics ---",
        f"Encounters: {journey.encounters_faced} (fled: {journey.encounters_fled})",
        f"Rest Stops: {journey.rest_count}",
        f"Supplies Used: {journey.supplies_consumed}",
        f"Shortcuts Found: {len(journey.shortcuts_found)}",
    ])

    return "\n".join(lines)


@command(
    name="weather",
    aliases=["forecast"],
    category=CommandCategory.INFO,
    help_text="Check the current weather conditions.",
)
async def cmd_weather(player_id: str, args: str, game_state) -> str:
    """Display current weather conditions."""
    from ..components.journey import WeatherType, RegionWeatherData
    from ..components.spatial import LocationData

    location = await game_state.get_component(player_id, "LocationData")
    if not location:
        return "You don't seem to be anywhere."

    # Try to get region weather
    region_weather = await game_state.get_component(location.room_id, "RegionWeatherData")

    if not region_weather:
        # Check if we're in a journey region
        journey = await game_state.get_component(player_id, "JourneyData")
        if journey and journey.is_active:
            region_weather = await game_state.get_component(
                journey.current_region, "RegionWeatherData"
            )

    if not region_weather:
        # Default indoor/static area response
        return "You are in a sheltered area. The weather outside doesn't affect you here."

    if region_weather.is_underground:
        return "You are underground. There is no weather here, only the eternal dark."

    weather = region_weather.current_weather
    lines = [
        "=== Current Weather ===",
        "",
        weather.get_description(),
        "",
    ]

    if weather.wind_strength > 0:
        wind_desc = _describe_wind(weather.wind_strength)
        lines.append(f"Wind: {wind_desc} from the {weather.wind_direction}")

    if weather.temperature_modifier != 0:
        temp_desc = _describe_temperature(weather.temperature_modifier)
        lines.append(f"Temperature: {temp_desc}")

    if weather.magical:
        lines.append("There is something unnatural about this weather...")

    # Effects on travel
    if weather.effective_movement_multiplier > 1.0:
        penalty = int((weather.effective_movement_multiplier - 1.0) * 100)
        lines.append(f"\nTravel is {penalty}% slower in these conditions.")

    if weather.effective_visibility_penalty > 30:
        lines.append("Visibility is significantly reduced.")

    return "\n".join(lines)


@command(
    name="supplies",
    aliases=["rations", "provisions"],
    category=CommandCategory.INFO,
    help_text="Check your travel supplies.",
)
async def cmd_supplies(player_id: str, args: str, game_state) -> str:
    """Display current supply levels."""
    from ..components.journey import SupplyData, SupplyType

    supplies = await game_state.get_component(player_id, "SupplyData")

    if not supplies or not supplies.supplies:
        return "You have no travel supplies. Consider buying some before a long journey."

    lines = ["=== Travel Supplies ===", ""]

    for supply_type in SupplyType:
        if supply_type in supplies.supplies:
            item = supplies.supplies[supply_type]
            quality_stars = "*" * item.quality
            lines.append(f"  {supply_type.value.title():20} {item.quantity:3} {quality_stars}")

    if supplies.consumption_rate != 1.0:
        if supplies.consumption_rate < 1.0:
            lines.append(f"\n(Consumption reduced to {supplies.consumption_rate:.0%})")
        else:
            lines.append(f"\n(Consumption increased to {supplies.consumption_rate:.0%})")

    return "\n".join(lines)


@command(
    name="mount",
    aliases=["steed", "ride"],
    category=CommandCategory.MOVEMENT,
    help_text="Manage your mount - mount/dismount, check status, or feed.",
)
async def cmd_mount(player_id: str, args: str, game_state) -> str:
    """Mount commands: status, mount, dismount, feed."""
    from ..components.journey import MountData, SupplyType, SupplyData

    mount = await game_state.get_component(player_id, "MountData")

    if not mount:
        return "You don't have a mount. Visit a stable to purchase one."

    parts = args.lower().split() if args else []
    subcommand = parts[0] if parts else "status"

    if subcommand == "status" or subcommand == "":
        return _mount_status(mount)

    elif subcommand in ["mount", "ride", "on"]:
        if mount.is_mounted:
            return f"You are already riding {mount.name}."
        if mount.current_stamina < 10:
            return f"{mount.name} is too exhausted to ride. Let them rest."
        mount.is_mounted = True
        return f"You mount {mount.name} and prepare to ride."

    elif subcommand in ["dismount", "off", "down"]:
        if not mount.is_mounted:
            return f"You are not riding {mount.name}."
        mount.is_mounted = False
        return f"You dismount from {mount.name}."

    elif subcommand == "feed":
        if mount.fed_today:
            return f"{mount.name} has already been fed today."

        supplies = await game_state.get_component(player_id, "SupplyData")
        if not supplies or not supplies.consume_supply(SupplyType.MOUNT_FEED, 1):
            return "You don't have any mount feed."

        mount.fed_today = True
        mount.current_stamina = min(mount.max_stamina, mount.current_stamina + 30)
        mount.loyalty = min(100, mount.loyalty + 2)
        return f"You feed {mount.name}. They seem pleased and more energetic."

    elif subcommand == "rest":
        if mount.is_mounted:
            return f"Dismount first before letting {mount.name} rest."
        mount.rest(hours=1)
        return f"{mount.name} rests and recovers some stamina."

    else:
        return "Usage: mount [status|mount|dismount|feed|rest]"


@command(
    name="eat",
    aliases=["consume"],
    category=CommandCategory.OBJECT,
    help_text="Eat food from your supplies.",
)
async def cmd_eat(player_id: str, args: str, game_state) -> str:
    """Consume food supplies."""
    from ..components.journey import SupplyData, SupplyType, JourneyData

    supplies = await game_state.get_component(player_id, "SupplyData")
    journey = await game_state.get_component(player_id, "JourneyData")

    if not supplies or not supplies.consume_supply(SupplyType.FOOD, 1):
        return "You don't have any food to eat."

    if journey:
        journey.eat()
        journey.consume_supplies(1)

    return "You eat some of your provisions. Your hunger is satisfied."


@command(
    name="drink",
    aliases=["quaff"],
    category=CommandCategory.OBJECT,
    help_text="Drink water from your supplies.",
)
async def cmd_drink(player_id: str, args: str, game_state) -> str:
    """Consume water supplies."""
    from ..components.journey import SupplyData, SupplyType, JourneyData

    supplies = await game_state.get_component(player_id, "SupplyData")
    journey = await game_state.get_component(player_id, "JourneyData")

    if not supplies or not supplies.consume_supply(SupplyType.WATER, 1):
        return "You don't have any water to drink."

    if journey:
        journey.drink()
        journey.consume_supplies(1)

    return "You drink some water. Your thirst is quenched."


@command(
    name="camp",
    aliases=["makecamp", "pitch"],
    category=CommandCategory.MOVEMENT,
    help_text="Set up camp to rest during a journey.",
)
async def cmd_camp(player_id: str, args: str, game_state) -> str:
    """Set up camp for extended rest during journey."""
    from ..components.journey import JourneyData, MountData, SupplyData, SupplyType
    from ..components.position import Position, PositionData

    journey = await game_state.get_component(player_id, "JourneyData")

    if not journey or not journey.is_active:
        return "You can only set up camp during a journey through wilderness."

    # Check position
    position = await game_state.get_component(player_id, "PositionData")
    if position and position.position == Position.SLEEPING:
        return "You are already resting."

    # Use supplies for camping
    supplies = await game_state.get_component(player_id, "SupplyData")
    torch_used = False
    if supplies:
        torch_used = supplies.consume_supply(SupplyType.TORCH, 1)

    # Record rest
    journey.record_rest()

    # Rest mount too
    mount = await game_state.get_component(player_id, "MountData")
    if mount:
        mount.is_mounted = False
        mount.rest(hours=2)

    lines = [
        "You set up a simple camp and take time to rest.",
        f"Your fatigue decreases. (Now: {journey.fatigue}%)",
        f"Your morale improves. (Now: {journey.morale}%)",
    ]

    if torch_used:
        lines.append("You light a torch to ward off the darkness.")
    if mount:
        lines.append(f"{mount.name} rests beside you.")

    return "\n".join(lines)


@command(
    name="waypoint",
    aliases=["wp", "waypoints"],
    category=CommandCategory.INFO,
    help_text="View discovered waypoints in the current region.",
)
async def cmd_waypoint(player_id: str, args: str, game_state) -> str:
    """Display discovered waypoints."""
    from ..components.journey import JourneyData

    journey = await game_state.get_component(player_id, "JourneyData")

    if not journey or not journey.is_active:
        return "Waypoints are only tracked during journeys through dynamic regions."

    if not journey.waypoints_discovered:
        return "You haven't discovered any waypoints in this region yet."

    lines = [
        f"=== Waypoints in {journey.current_region.replace('_', ' ').title()} ===",
        "",
    ]

    for i, wp_name in enumerate(journey.waypoints_discovered, 1):
        visited = any(v.waypoint_name == wp_name for v in journey.waypoints_visited)
        status = "[Visited]" if visited else "[Discovered]"
        lines.append(f"  {i}. {wp_name} {status}")

    if journey.next_waypoint:
        lines.append(f"\nNext waypoint: {journey.next_waypoint}")

    if journey.shortcuts_found:
        lines.append(f"\nShortcuts discovered: {len(journey.shortcuts_found)}")

    return "\n".join(lines)


# Helper functions

def _make_bar(value: int, max_value: int, width: int, reverse: bool = False) -> str:
    """Create a text progress bar."""
    filled = int((value / max_value) * width)
    if reverse:
        # For fatigue, more = worse, so invert the visual
        return "=" * (width - filled) + "-" * filled
    return "=" * filled + "-" * (width - filled)


def _describe_wind(strength: int) -> str:
    """Describe wind strength."""
    if strength < 10:
        return "Calm"
    elif strength < 30:
        return "Light breeze"
    elif strength < 50:
        return "Moderate wind"
    elif strength < 70:
        return "Strong wind"
    elif strength < 90:
        return "Gale"
    else:
        return "Hurricane-force winds"


def _describe_temperature(modifier: int) -> str:
    """Describe temperature relative to normal."""
    if modifier < -20:
        return "Dangerously cold"
    elif modifier < -10:
        return "Very cold"
    elif modifier < -5:
        return "Cold"
    elif modifier < 5:
        return "Comfortable"
    elif modifier < 10:
        return "Warm"
    elif modifier < 20:
        return "Hot"
    else:
        return "Dangerously hot"


def _mount_status(mount) -> str:
    """Generate mount status display."""
    stamina_bar = _make_bar(mount.current_stamina, mount.max_stamina, 20)
    loyalty_bar = _make_bar(mount.loyalty, 100, 20)

    lines = [
        f"=== {mount.name} ({mount.mount_type.value.replace('_', ' ').title()}) ===",
        "",
        f"Status: {'Mounted' if mount.is_mounted else 'Resting'}",
        f"Training Level: {mount.training_level}/5",
        "",
        f"Stamina: [{stamina_bar}] {mount.current_stamina}/{mount.max_stamina}",
        f"Loyalty: [{loyalty_bar}] {mount.loyalty}/100",
        "",
        f"Speed Bonus: {mount.effective_speed:.1f}x",
        f"Fed Today: {'Yes' if mount.fed_today else 'No'}",
    ]

    # Terrain bonuses
    bonuses = mount.mount_type.terrain_bonuses
    if bonuses:
        lines.append("\nTerrain Bonuses:")
        for terrain, bonus in bonuses.items():
            lines.append(f"  {terrain.title()}: +{int((bonus - 1) * 100)}%")

    return "\n".join(lines)
