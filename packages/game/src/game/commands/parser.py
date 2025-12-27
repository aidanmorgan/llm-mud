"""
Command Parser

Parses raw player input into structured commands.
Supports command abbreviations and argument parsing.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class ParsedCommand:
    """Represents a parsed player command."""

    raw: str  # Original input
    command: str  # The command word (lowercase)
    args: List[str] = field(default_factory=list)  # Arguments
    target: Optional[str] = None  # Primary target (first arg often)
    quantity: int = 1  # For "get 5 coins" style commands

    @property
    def arg_string(self) -> str:
        """Get all arguments as a single string."""
        return " ".join(self.args)

    def get_arg(self, index: int, default: str = "") -> str:
        """Get argument at index, or default if not present."""
        if 0 <= index < len(self.args):
            return self.args[index]
        return default


class CommandParser:
    """
    Parses player commands with abbreviation support.

    Features:
    - Command abbreviation matching (n -> north, l -> look)
    - Quantity prefixes (get 5 coins)
    - Target.object notation (get sword.ground)
    - Quoted strings for multi-word arguments
    """

    # Direction abbreviations
    DIRECTION_ABBREVS = {
        "n": "north",
        "s": "south",
        "e": "east",
        "w": "west",
        "u": "up",
        "d": "down",
        "ne": "northeast",
        "nw": "northwest",
        "se": "southeast",
        "sw": "southwest",
    }

    # Common command abbreviations
    COMMAND_ABBREVS = {
        "l": "look",
        "i": "inventory",
        "inv": "inventory",
        "eq": "equipment",
        "k": "kill",
        "fl": "flee",
        "sc": "score",
        "who": "who",
        "'": "say",
        '"': "say",
        ";": "emote",
        ":": "emote",
        "wh": "whisper",
        "sh": "shout",
        "ex": "exits",
        "exa": "examine",
        "g": "get",
        "dr": "drop",
        "p": "put",
        "gi": "give",
        "we": "wear",
        "rem": "remove",
        "rec": "recall",
        "sa": "save",
        "qu": "quit",
        "af": "affects",
        "pra": "practice",
        "tr": "train",
        "whe": "where",
        "hel": "help",
        "sco": "score",
        "stat": "stats",
        "res": "rest",
        "sl": "sleep",
        "wa": "wake",
        "sta": "stand",
        "si": "sit",
    }

    def __init__(self):
        # Build expanded abbreviation lookup
        self._abbrevs = {}
        self._abbrevs.update(self.DIRECTION_ABBREVS)
        self._abbrevs.update(self.COMMAND_ABBREVS)

    def parse(self, raw_input: str) -> ParsedCommand:
        """Parse raw input into a structured command."""
        raw_input = raw_input.strip()
        if not raw_input:
            return ParsedCommand(raw="", command="")

        # Handle special single-character commands
        if raw_input[0] in ("'", '"'):
            # Say command with quote prefix
            return ParsedCommand(
                raw=raw_input,
                command="say",
                args=[raw_input[1:].strip()] if len(raw_input) > 1 else [],
            )

        if raw_input[0] in (";", ":"):
            # Emote command
            return ParsedCommand(
                raw=raw_input,
                command="emote",
                args=[raw_input[1:].strip()] if len(raw_input) > 1 else [],
            )

        # Tokenize the input
        tokens = self._tokenize(raw_input)
        if not tokens:
            return ParsedCommand(raw=raw_input, command="")

        # First token is the command
        command = tokens[0].lower()
        args = tokens[1:] if len(tokens) > 1 else []

        # Expand abbreviation
        command = self._expand_abbreviation(command)

        # Check for quantity prefix in first argument
        quantity = 1
        if args and args[0].isdigit():
            quantity = int(args[0])
            args = args[1:]

        # First argument is often the target
        target = args[0] if args else None

        return ParsedCommand(
            raw=raw_input,
            command=command,
            args=args,
            target=target,
            quantity=quantity,
        )

    def _tokenize(self, text: str) -> List[str]:
        """
        Tokenize input, respecting quoted strings.

        Examples:
            'kill goblin' -> ['kill', 'goblin']
            'say "hello world"' -> ['say', 'hello world']
            'get 5 gold' -> ['get', '5', 'gold']
        """
        tokens = []
        current = ""
        in_quotes = False
        quote_char = None

        for char in text:
            if char in ('"', "'") and not in_quotes:
                in_quotes = True
                quote_char = char
            elif char == quote_char and in_quotes:
                in_quotes = False
                quote_char = None
                if current:
                    tokens.append(current)
                    current = ""
            elif char == " " and not in_quotes:
                if current:
                    tokens.append(current)
                    current = ""
            else:
                current += char

        if current:
            tokens.append(current)

        return tokens

    def _expand_abbreviation(self, command: str) -> str:
        """Expand a command abbreviation to full command."""
        # Check exact match first
        if command in self._abbrevs:
            return self._abbrevs[command]

        # For partial matches, we'd need the full command list
        # For now, just return as-is
        return command

    def add_abbreviation(self, abbrev: str, full_command: str) -> None:
        """Add a custom abbreviation."""
        self._abbrevs[abbrev.lower()] = full_command.lower()

    def parse_target(self, target: str) -> Tuple[str, Optional[str]]:
        """
        Parse target.container notation.

        Examples:
            'sword' -> ('sword', None)
            'sword.ground' -> ('sword', 'ground')
            '2.sword.bag' -> ('2.sword', 'bag')
        """
        if "." in target:
            parts = target.rsplit(".", 1)
            return parts[0], parts[1]
        return target, None

    def parse_ordinal_target(self, target: str) -> Tuple[int, str]:
        """
        Parse N.target notation for selecting Nth item.

        Examples:
            'sword' -> (1, 'sword')
            '2.sword' -> (2, 'sword')
            '3.bag' -> (3, 'bag')
        """
        if "." in target:
            parts = target.split(".", 1)
            if parts[0].isdigit():
                return int(parts[0]), parts[1]
        return 1, target
