from aiogram import BaseMiddleware
from typing import Callable, Awaitable, Dict, Any
from aiogram.types import TelegramObject
from sqlalchemy import select
from src.config import settings
from src.database import SessionLocal
from src.models import User, Role

class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if not tg_user:
            return await handler(event, data)
        if getattr(tg_user, "is_bot", False):
            print(f"[INFO] Ignoring bot user update: {tg_user.id}")
            return None
        async with SessionLocal() as session:
            result = await session.execute(select(User).where(User.tg_id == tg_user.id))
            user = result.scalar_one_or_none()
            if user and tg_user.id in settings.admin_ids and user.role != Role.admin:
                user.role = Role.admin
                await session.commit()
            if not user and tg_user.id in settings.admin_ids:
                user = User(tg_id=tg_user.id, role=Role.admin, full_name=tg_user.full_name)
                session.add(user)
                await session.commit()
            data["db_session"] = session
            data["current_user"] = user
            return await handler(event, data)
