"""
ANSI to HTML Converter

Converts ANSI escape codes and MUD color codes to HTML with CSS classes.
"""

import re
from typing import Dict

# MUD-style color codes: {r} = red, {g} = green, etc.
MUD_COLOR_CODES: Dict[str, str] = {
    "{x}": "</span>",  # Reset
    "{X}": "</span>",
    "{d}": '<span class="ansi-black">',  # Dark/Black
    "{D}": '<span class="ansi-bright-black">',
    "{r}": '<span class="ansi-red">',
    "{R}": '<span class="ansi-bright-red">',
    "{g}": '<span class="ansi-green">',
    "{G}": '<span class="ansi-bright-green">',
    "{y}": '<span class="ansi-yellow">',
    "{Y}": '<span class="ansi-bright-yellow">',
    "{b}": '<span class="ansi-blue">',
    "{B}": '<span class="ansi-bright-blue">',
    "{m}": '<span class="ansi-magenta">',
    "{M}": '<span class="ansi-bright-magenta">',
    "{c}": '<span class="ansi-cyan">',
    "{C}": '<span class="ansi-bright-cyan">',
    "{w}": '<span class="ansi-white">',
    "{W}": '<span class="ansi-bright-white">',
}

# ANSI escape code to CSS class mapping
ANSI_CODES: Dict[int, str] = {
    0: "ansi-reset",
    1: "ansi-bold",
    4: "ansi-underline",
    30: "ansi-black",
    31: "ansi-red",
    32: "ansi-green",
    33: "ansi-yellow",
    34: "ansi-blue",
    35: "ansi-magenta",
    36: "ansi-cyan",
    37: "ansi-white",
    90: "ansi-bright-black",
    91: "ansi-bright-red",
    92: "ansi-bright-green",
    93: "ansi-bright-yellow",
    94: "ansi-bright-blue",
    95: "ansi-bright-magenta",
    96: "ansi-bright-cyan",
    97: "ansi-bright-white",
}

# Regex to match ANSI escape sequences
ANSI_PATTERN = re.compile(r"\x1b\[([0-9;]*)m")

# Regex to match MUD color codes
MUD_PATTERN = re.compile(r"\{([xXdDrRgGyYbBmMcCwW])\}")


def ansi_to_html(text: str) -> str:
    """
    Convert ANSI escape codes and MUD color codes to HTML.

    Handles:
    - ANSI escape sequences (ESC[Xm)
    - MUD-style color codes ({r}, {g}, etc.)
    - HTML entity escaping
    """
    # First, escape HTML entities
    text = html_escape(text)

    # Convert MUD color codes
    text = convert_mud_codes(text)

    # Convert ANSI escape codes
    text = convert_ansi_codes(text)

    return text


def html_escape(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def convert_mud_codes(text: str) -> str:
    """Convert MUD-style color codes to HTML spans."""
    for code, html in MUD_COLOR_CODES.items():
        text = text.replace(code, html)
    return text


def convert_ansi_codes(text: str) -> str:
    """Convert ANSI escape codes to HTML spans."""
    result = []
    last_end = 0
    open_spans = 0

    for match in ANSI_PATTERN.finditer(text):
        # Add text before this match
        result.append(text[last_end : match.start()])

        # Parse the ANSI codes
        codes_str = match.group(1)
        if not codes_str:
            codes = [0]
        else:
            codes = [int(c) for c in codes_str.split(";") if c]

        for code in codes:
            if code == 0:
                # Reset - close all open spans
                result.append("</span>" * open_spans)
                open_spans = 0
            elif code in ANSI_CODES:
                css_class = ANSI_CODES[code]
                result.append(f'<span class="{css_class}">')
                open_spans += 1

        last_end = match.end()

    # Add remaining text
    result.append(text[last_end:])

    # Close any remaining open spans
    result.append("</span>" * open_spans)

    return "".join(result)


def strip_colors(text: str) -> str:
    """Remove all color codes from text."""
    # Remove MUD codes
    text = MUD_PATTERN.sub("", text)
    # Remove ANSI codes
    text = ANSI_PATTERN.sub("", text)
    return text


# CSS styles for ANSI colors
ANSI_CSS = """
/* ANSI Color Styles */
.ansi-reset { }
.ansi-bold { font-weight: bold; }
.ansi-underline { text-decoration: underline; }

/* Normal colors */
.ansi-black { color: #000000; }
.ansi-red { color: #cc0000; }
.ansi-green { color: #00cc00; }
.ansi-yellow { color: #cccc00; }
.ansi-blue { color: #0000cc; }
.ansi-magenta { color: #cc00cc; }
.ansi-cyan { color: #00cccc; }
.ansi-white { color: #cccccc; }

/* Bright colors */
.ansi-bright-black { color: #666666; }
.ansi-bright-red { color: #ff0000; }
.ansi-bright-green { color: #00ff00; }
.ansi-bright-yellow { color: #ffff00; }
.ansi-bright-blue { color: #0000ff; }
.ansi-bright-magenta { color: #ff00ff; }
.ansi-bright-cyan { color: #00ffff; }
.ansi-bright-white { color: #ffffff; }
"""
