from aiogram import BaseMiddleware
from typing import Callable, Awaitable, Dict, Any
from aiogram.types import TelegramObject
from sqlalchemy import select
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
        async with SessionLocal() as session:
            result = await session.execute(select(User).where(User.tg_id == tg_user.id))
            user = result.scalar_one_or_none()
            data["db_session"] = session
            data["current_user"] = user
            return await handler(event, data)
