"""Compatibility layer that re-exports the fixed broadcast plugin."""

from .feature_broadcast_aiogram_plugin_fixed import (
    BroadcastStates,
    add_user,
    build_broadcast_router,
    chunk_text,
    get_all_users,
    get_broadcast_admin_button,
    register_user_from_message,
    users_count,
)

__all__ = [
    "BroadcastStates",
    "add_user",
    "build_broadcast_router",
    "chunk_text",
    "get_all_users",
    "get_broadcast_admin_button",
    "register_user_from_message",
    "users_count",
]
