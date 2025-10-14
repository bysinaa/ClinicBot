from __future__ import annotations

from typing import Sequence, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import OnlineConsultRequest, OnlineConsultRequestStatus, User


async def create_request(session: AsyncSession, user: User, question: str) -> OnlineConsultRequest:
    request = OnlineConsultRequest(user_id=user.id, question=question.strip())
    session.add(request)
    await session.commit()
    await session.refresh(request)
    return request


async def attach_receipt(
    session: AsyncSession,
    request_id: int,
    file_id: str,
) -> bool:
    request = await session.get(OnlineConsultRequest, request_id)
    if not request:
        return False
    request.receipt_file_id = file_id
    request.status = OnlineConsultRequestStatus.awaiting_confirmation
    await session.commit()
    return True


async def update_status(
    session: AsyncSession,
    request_id: int,
    status: OnlineConsultRequestStatus,
    *,
    admin_notes: str | None = None,
    answer: str | None = None,
) -> bool:
    request = await session.get(OnlineConsultRequest, request_id)
    if not request:
        return False
    request.status = status
    if admin_notes is not None:
        request.admin_notes = admin_notes
    if answer is not None:
        request.answer = answer
    await session.commit()
    return True


async def list_requests(
    session: AsyncSession,
    *,
    status: OnlineConsultRequestStatus | None = None,
    limit: int = 20,
) -> Sequence[OnlineConsultRequest]:
    query = select(OnlineConsultRequest).order_by(OnlineConsultRequest.created_at.desc())
    if status is not None:
        query = query.where(OnlineConsultRequest.status == status)
    result = await session.execute(query.limit(limit))
    return result.scalars().all()


async def get_request(session: AsyncSession, request_id: int) -> OnlineConsultRequest | None:
    return await session.get(OnlineConsultRequest, request_id)


async def get_latest_request_for_user(
    session: AsyncSession,
    user_id: int,
) -> Optional[OnlineConsultRequest]:
    result = await session.execute(
        select(OnlineConsultRequest)
        .where(OnlineConsultRequest.user_id == user_id)
        .order_by(OnlineConsultRequest.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def user_has_active_request(session: AsyncSession, user_id: int) -> bool:
    result = await session.execute(
        select(OnlineConsultRequest)
        .where(
            OnlineConsultRequest.user_id == user_id,
            OnlineConsultRequest.status.in_(
                [
                    OnlineConsultRequestStatus.pending,
                    OnlineConsultRequestStatus.awaiting_confirmation,
                    OnlineConsultRequestStatus.approved,
                ]
            ),
        )
        .order_by(OnlineConsultRequest.created_at.desc())
        .limit(1)
    )
    return result.scalars().first() is not None
