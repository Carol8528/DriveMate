"""Public view exports for the Streamlit composition root."""

from views.chat import render_drivemate_chat
from views.cockpit import render_cockpit_context
from views.command import render_command_workspace
from views.context import WorkspaceContext

__all__ = [
    "WorkspaceContext",
    "render_cockpit_context",
    "render_command_workspace",
    "render_drivemate_chat",
]
