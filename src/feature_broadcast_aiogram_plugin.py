"""Backward-compatibility shim for the broadcast feature module."""

from src.services.feature_broadcast_aiogram_plugin import (
    build_broadcast_router,
    get_broadcast_admin_button,
    register_user_from_message,
)

__all__ = [
    "build_broadcast_router",
    "get_broadcast_admin_button",
    "register_user_from_message",
]
