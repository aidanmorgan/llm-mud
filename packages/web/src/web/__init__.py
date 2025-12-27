"""
LLM-MUD Web Client

HTMX-based browser client for playing the MUD through a web browser.
"""

from .server import app, create_app
from .session import WebSession, WebSessionManager, WebSessionState
from .ansi import ansi_to_html, strip_colors, ANSI_CSS
from .templates_config import templates, get_templates, get_static_files

__all__ = [
    "app",
    "create_app",
    "WebSession",
    "WebSessionManager",
    "WebSessionState",
    "ansi_to_html",
    "strip_colors",
    "ANSI_CSS",
    "templates",
    "get_templates",
    "get_static_files",
]
