from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Sequence

JsonObject = Dict[str, Any]


@dataclass(frozen=True)
class WorkspaceContext:
    """Explicit UI dependencies supplied by the Streamlit composition root."""

    state: Any
    api_mode: str
    client: Any
    drivemate_avatar: str
    user_avatar: str
    owner_quick_actions: Sequence[tuple[str, str]]
    taxi_quick_actions: Sequence[tuple[str, str]]
    engine_labels: Mapping[str, str]
    status_labels: Mapping[str, str]
    risk_labels: Mapping[str, str]
    submit_message: Callable[[str], None]
    handle_engine_change: Callable[[], None]
    update_run: Callable[[str], None]
    sync_cabin_temp: Callable[[], None]
    sync_seat_angle: Callable[[], None]
    sync_window_percent: Callable[[], None]
    sync_ambient_light: Callable[[], None]
    sync_center_view: Callable[[], None]
    build_snapshot: Callable[[], JsonObject]
    pending_steps: Callable[[JsonObject], List[JsonObject]]
    advance_simulation: Callable[[], None]
