"""
LLM-MUD Extensions Package

This package contains extensions that add content and functionality
to the LLM-MUD server.
"""

from .sample_extension import SampleExtension

__all__ = [
    "SampleExtension",
]


def hello() -> str:
    return "Hello from extensions!"
