"""
Command System

Handles parsing and execution of player commands.
Supports abbreviations (e.g., 'n' for 'north', 'l' for 'look').
"""

from .parser import CommandParser, ParsedCommand
from .registry import CommandRegistry, command, get_command_registry
from .handler import CommandHandler

__all__ = [
    "CommandParser",
    "ParsedCommand",
    "CommandRegistry",
    "command",
    "get_command_registry",
    "CommandHandler",
]
