"""AWORG's tooling: Capabilities, the Tools inside them, and the Registry.

Each subdirectory here is a Capability and each module inside one is a Tool.
Nothing needs registering: putting a file in a folder is how a tool arrives.
"""

from .base import ToolContext, ToolError, ToolResult, ToolSpec, size_for_model
from .registry import Capability, Registry

__all__ = [
    "Capability",
    "Registry",
    "ToolContext",
    "ToolError",
    "ToolResult",
    "ToolSpec",
    "size_for_model",
]
