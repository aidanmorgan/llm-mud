"""Jinja2 template configuration for the web application."""

from pathlib import Path

from fastapi.templating import Jinja2Templates
from starlette.staticfiles import StaticFiles


# Template directory path
TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

# Jinja2 templates instance
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_templates() -> Jinja2Templates:
    """Get the Jinja2 templates instance."""
    return templates


def get_static_files() -> StaticFiles:
    """Get static files mount for FastAPI."""
    return StaticFiles(directory=str(STATIC_DIR))
