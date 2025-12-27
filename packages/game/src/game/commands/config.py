"""Configuration and preference commands."""

from typing import Optional

from ..commands.registry import command, CommandCategory
from ..components.preferences import (
    PreferencesData,
    ColorTheme,
    DEFAULT_PROMPT,
    DEFAULT_BATTLE_PROMPT,
    PromptToken,
)


@command(
    name="config",
    aliases=["settings", "options", "prefs"],
    category=CommandCategory.INFO,
    help_text="View or change your configuration settings.",
)
async def cmd_config(player_id: str, args: str, game_state) -> str:
    """View or change configuration settings."""
    prefs = await game_state.get_component(player_id, "PreferencesData")
    if not prefs:
        prefs = PreferencesData()
        await game_state.set_component(player_id, "PreferencesData", prefs)

    if not args:
        # Display all settings
        settings = prefs.get_display_settings()
        lines = [
            "=== Configuration Settings ===",
            "",
            "Display:",
        ]
        display_keys = ["Brief Mode", "Compact Mode", "Color", "Color Theme",
                        "Page Length", "Line Width"]
        for key in display_keys:
            lines.append(f"  {key}: {settings[key]}")

        lines.append("")
        lines.append("Auto-Actions:")
        auto_keys = ["Auto-loot", "Auto-gold", "Auto-sac", "Auto-exit",
                     "Auto-split", "Auto-assist"]
        for key in auto_keys:
            lines.append(f"  {key}: {settings[key]}")

        lines.append("")
        lines.append("Channels:")
        channel_keys = ["Tells", "Shouts", "OOC Channel", "Trade Channel",
                        "Newbie Channel"]
        for key in channel_keys:
            lines.append(f"  {key}: {settings[key]}")

        lines.append("")
        lines.append("Prompts:")
        lines.append(f"  Normal: {prefs.prompt}")
        lines.append(f"  Battle: {prefs.battle_prompt}")

        lines.append("")
        lines.append("Use 'toggle <setting>' to change boolean settings.")
        lines.append("Use 'prompt <format>' to change your prompt.")
        lines.append("Use 'config theme <name>' to change color theme.")

        return "\n".join(lines)

    # Handle subcommands
    parts = args.split(None, 1)
    subcmd = parts[0].lower()
    subargs = parts[1] if len(parts) > 1 else ""

    if subcmd == "theme":
        if not subargs:
            themes = [t.value for t in ColorTheme]
            return f"Available themes: {', '.join(themes)}\nCurrent: {prefs.color_theme.value}"

        theme_name = subargs.lower()
        try:
            new_theme = ColorTheme(theme_name)
            prefs.color_theme = new_theme
            await game_state.set_component(player_id, "PreferencesData", prefs)
            return f"Color theme set to: {new_theme.value}"
        except ValueError:
            themes = [t.value for t in ColorTheme]
            return f"Unknown theme. Available: {', '.join(themes)}"

    elif subcmd == "pagesize" or subcmd == "page":
        if not subargs:
            return f"Page length: {prefs.page_length} (0 = off)"
        try:
            size = int(subargs)
            if size < 0:
                return "Page size must be 0 or greater."
            prefs.page_length = size
            await game_state.set_component(player_id, "PreferencesData", prefs)
            if size == 0:
                return "Paging disabled."
            return f"Page length set to {size} lines."
        except ValueError:
            return "Usage: config pagesize <number>"

    elif subcmd == "width" or subcmd == "linewidth":
        if not subargs:
            return f"Line width: {prefs.line_width} (0 = off)"
        try:
            width = int(subargs)
            if width < 0:
                return "Width must be 0 or greater."
            if width > 0 and width < 40:
                return "Width must be at least 40 or 0 (disabled)."
            prefs.line_width = width
            await game_state.set_component(player_id, "PreferencesData", prefs)
            if width == 0:
                return "Line wrapping disabled."
            return f"Line width set to {width} characters."
        except ValueError:
            return "Usage: config width <number>"

    return "Unknown config option. Use 'config' to see available settings."


@command(
    name="toggle",
    aliases=["tog"],
    category=CommandCategory.INFO,
    help_text="Toggle a boolean setting on or off.",
)
async def cmd_toggle(player_id: str, args: str, game_state) -> str:
    """Toggle a boolean setting."""
    prefs = await game_state.get_component(player_id, "PreferencesData")
    if not prefs:
        prefs = PreferencesData()
        await game_state.set_component(player_id, "PreferencesData", prefs)

    if not args:
        lines = [
            "=== Toggleable Settings ===",
            "",
            "Display: brief, compact, color",
            "Auto-actions: autoloot, autogold, autosac, autoexit, autosplit, autoassist",
            "Channels: tell, shout, ooc, trade, newbie",
            "",
            "Usage: toggle <setting>",
        ]
        return "\n".join(lines)

    setting = args.split()[0].lower()
    new_value = prefs.toggle(setting)

    if new_value is None:
        return f"Unknown setting: {setting}. Use 'toggle' to see available options."

    await game_state.set_component(player_id, "PreferencesData", prefs)

    state = "ON" if new_value else "OFF"
    return f"{setting.title()} is now {state}."


@command(
    name="prompt",
    aliases=[],
    category=CommandCategory.INFO,
    help_text="Customize your command prompt.",
)
async def cmd_prompt(player_id: str, args: str, game_state) -> str:
    """Customize the command prompt."""
    prefs = await game_state.get_component(player_id, "PreferencesData")
    if not prefs:
        prefs = PreferencesData()
        await game_state.set_component(player_id, "PreferencesData", prefs)

    if not args:
        lines = [
            "=== Prompt Customization ===",
            "",
            f"Current prompt: {prefs.prompt}",
            f"Battle prompt: {prefs.battle_prompt}",
            "",
            "Available tokens:",
            "  %h/%H - Current/Max HP",
            "  %m/%M - Current/Max Mana",
            "  %s/%S - Current/Max Stamina",
            "  %x/%X - XP / XP to next level",
            "  %g    - Gold",
            "  %l    - Level",
            "  %r    - Room name",
            "  %z    - Zone name",
            "  %e    - Exits",
            "  %t    - Game time",
            "  %w    - Weather",
            "  %T    - Target name",
            "  %P    - Target HP %",
            "  %n    - Newline",
            "  %%    - Literal %",
            "",
            "Usage: prompt <format>",
            "       prompt battle <format>",
            "       prompt reset",
        ]
        return "\n".join(lines)

    parts = args.split(None, 1)
    subcmd = parts[0].lower()

    if subcmd == "reset":
        prefs.prompt = DEFAULT_PROMPT
        prefs.battle_prompt = DEFAULT_BATTLE_PROMPT
        await game_state.set_component(player_id, "PreferencesData", prefs)
        return "Prompts reset to defaults."

    if subcmd == "battle":
        if len(parts) < 2:
            return f"Current battle prompt: {prefs.battle_prompt}"
        prefs.battle_prompt = parts[1]
        await game_state.set_component(player_id, "PreferencesData", prefs)
        return f"Battle prompt set to: {prefs.battle_prompt}"

    # Set normal prompt
    prefs.prompt = args
    await game_state.set_component(player_id, "PreferencesData", prefs)
    return f"Prompt set to: {prefs.prompt}"


@command(
    name="alias",
    aliases=["aliases"],
    category=CommandCategory.INFO,
    help_text="Create command shortcuts.",
)
async def cmd_alias(player_id: str, args: str, game_state) -> str:
    """Manage command aliases."""
    prefs = await game_state.get_component(player_id, "PreferencesData")
    if not prefs:
        prefs = PreferencesData()
        await game_state.set_component(player_id, "PreferencesData", prefs)

    if not args:
        # List all aliases
        if not prefs.aliases:
            return "You have no aliases defined. Use 'alias <name> <command>' to create one."

        lines = [
            "=== Your Aliases ===",
            "",
        ]
        for name, alias_data in sorted(prefs.aliases.items()):
            lines.append(f"  {name} = {alias_data.expansion}")

        lines.append("")
        lines.append(f"({len(prefs.aliases)}/{prefs.max_aliases} aliases used)")
        lines.append("")
        lines.append("Usage: alias <name> <command>")
        lines.append("       unalias <name>")

        return "\n".join(lines)

    parts = args.split(None, 1)
    name = parts[0].lower()

    if len(parts) == 1:
        # Show specific alias
        expansion = prefs.get_alias(name)
        if expansion:
            return f"Alias '{name}' = {expansion}"
        return f"No alias named '{name}'."

    expansion = parts[1]

    # Prevent alias loops
    if expansion.split()[0].lower() == name:
        return "Cannot create self-referencing alias."

    # Prevent overwriting built-in commands
    cmd_def = await game_state.get_command(name)
    if cmd_def:
        return f"Cannot override built-in command '{name}'."

    if prefs.add_alias(name, expansion):
        await game_state.set_component(player_id, "PreferencesData", prefs)
        return f"Alias created: {name} = {expansion}"
    else:
        return f"Cannot add alias. You have reached the maximum of {prefs.max_aliases}."


@command(
    name="unalias",
    aliases=[],
    category=CommandCategory.INFO,
    help_text="Remove a command alias.",
)
async def cmd_unalias(player_id: str, args: str, game_state) -> str:
    """Remove a command alias."""
    prefs = await game_state.get_component(player_id, "PreferencesData")
    if not prefs:
        return "You have no aliases to remove."

    if not args:
        return "Usage: unalias <name>"

    name = args.split()[0].lower()

    if prefs.remove_alias(name):
        await game_state.set_component(player_id, "PreferencesData", prefs)
        return f"Alias '{name}' removed."

    return f"No alias named '{name}'."


@command(
    name="brief",
    aliases=[],
    category=CommandCategory.INFO,
    help_text="Toggle brief mode (short room descriptions).",
)
async def cmd_brief(player_id: str, args: str, game_state) -> str:
    """Toggle brief mode."""
    prefs = await game_state.get_component(player_id, "PreferencesData")
    if not prefs:
        prefs = PreferencesData()

    prefs.brief_mode = not prefs.brief_mode
    await game_state.set_component(player_id, "PreferencesData", prefs)

    if prefs.brief_mode:
        return "Brief mode ON. You will see short room descriptions."
    return "Brief mode OFF. You will see full room descriptions."


@command(
    name="compact",
    aliases=[],
    category=CommandCategory.INFO,
    help_text="Toggle compact mode (reduced whitespace).",
)
async def cmd_compact(player_id: str, args: str, game_state) -> str:
    """Toggle compact mode."""
    prefs = await game_state.get_component(player_id, "PreferencesData")
    if not prefs:
        prefs = PreferencesData()

    prefs.compact_mode = not prefs.compact_mode
    await game_state.set_component(player_id, "PreferencesData", prefs)

    if prefs.compact_mode:
        return "Compact mode ON."
    return "Compact mode OFF."


@command(
    name="color",
    aliases=["colour", "colors", "colours"],
    category=CommandCategory.INFO,
    help_text="Toggle or configure color display.",
)
async def cmd_color(player_id: str, args: str, game_state) -> str:
    """Toggle or configure colors."""
    prefs = await game_state.get_component(player_id, "PreferencesData")
    if not prefs:
        prefs = PreferencesData()

    if not args:
        prefs.color_enabled = not prefs.color_enabled
        await game_state.set_component(player_id, "PreferencesData", prefs)

        if prefs.color_enabled:
            return "Colors enabled."
        return "Colors disabled."

    # Handle theme selection
    theme_name = args.lower()
    try:
        new_theme = ColorTheme(theme_name)
        prefs.color_theme = new_theme
        prefs.color_enabled = True
        await game_state.set_component(player_id, "PreferencesData", prefs)
        return f"Color theme set to: {new_theme.value}"
    except ValueError:
        themes = [t.value for t in ColorTheme]
        return f"Unknown theme. Available: {', '.join(themes)}"


@command(
    name="autoloot",
    aliases=[],
    category=CommandCategory.INFO,
    help_text="Toggle automatic looting of corpses.",
)
async def cmd_autoloot(player_id: str, args: str, game_state) -> str:
    """Toggle autoloot."""
    prefs = await game_state.get_component(player_id, "PreferencesData")
    if not prefs:
        prefs = PreferencesData()

    prefs.autoloot = not prefs.autoloot
    await game_state.set_component(player_id, "PreferencesData", prefs)

    if prefs.autoloot:
        return "You will now automatically loot corpses."
    return "You will no longer automatically loot corpses."


@command(
    name="autogold",
    aliases=[],
    category=CommandCategory.INFO,
    help_text="Toggle automatic gold pickup from corpses.",
)
async def cmd_autogold(player_id: str, args: str, game_state) -> str:
    """Toggle autogold."""
    prefs = await game_state.get_component(player_id, "PreferencesData")
    if not prefs:
        prefs = PreferencesData()

    prefs.autogold = not prefs.autogold
    await game_state.set_component(player_id, "PreferencesData", prefs)

    if prefs.autogold:
        return "You will now automatically pick up gold from corpses."
    return "You will no longer automatically pick up gold from corpses."


@command(
    name="autosac",
    aliases=["autosacrifice"],
    category=CommandCategory.INFO,
    help_text="Toggle automatic sacrifice of corpses.",
)
async def cmd_autosac(player_id: str, args: str, game_state) -> str:
    """Toggle autosac."""
    prefs = await game_state.get_component(player_id, "PreferencesData")
    if not prefs:
        prefs = PreferencesData()

    prefs.autosac = not prefs.autosac
    await game_state.set_component(player_id, "PreferencesData", prefs)

    if prefs.autosac:
        return "You will now automatically sacrifice corpses."
    return "You will no longer automatically sacrifice corpses."


@command(
    name="autoexit",
    aliases=["autoexits"],
    category=CommandCategory.INFO,
    help_text="Toggle automatic display of exits in rooms.",
)
async def cmd_autoexit(player_id: str, args: str, game_state) -> str:
    """Toggle autoexit."""
    prefs = await game_state.get_component(player_id, "PreferencesData")
    if not prefs:
        prefs = PreferencesData()

    prefs.autoexit = not prefs.autoexit
    await game_state.set_component(player_id, "PreferencesData", prefs)

    if prefs.autoexit:
        return "You will now automatically see exits when entering rooms."
    return "Exits will no longer be shown automatically."


@command(
    name="autosplit",
    aliases=[],
    category=CommandCategory.INFO,
    help_text="Toggle automatic gold splitting with group.",
)
async def cmd_autosplit(player_id: str, args: str, game_state) -> str:
    """Toggle autosplit."""
    prefs = await game_state.get_component(player_id, "PreferencesData")
    if not prefs:
        prefs = PreferencesData()

    prefs.autosplit = not prefs.autosplit
    await game_state.set_component(player_id, "PreferencesData", prefs)

    if prefs.autosplit:
        return "You will now automatically split gold with your group."
    return "You will no longer automatically split gold."


@command(
    name="autoassist",
    aliases=[],
    category=CommandCategory.INFO,
    help_text="Toggle automatic assist in group combat.",
)
async def cmd_autoassist(player_id: str, args: str, game_state) -> str:
    """Toggle autoassist."""
    prefs = await game_state.get_component(player_id, "PreferencesData")
    if not prefs:
        prefs = PreferencesData()

    prefs.autoassist = not prefs.autoassist
    await game_state.set_component(player_id, "PreferencesData", prefs)

    if prefs.autoassist:
        return "You will now automatically assist group members in combat."
    return "You will no longer automatically assist in combat."
