# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date, time

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.database import Base
from src.models import ScheduleDay
from src.services.booking import SlotOverlapError, create_schedule_slot


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_schedule_slot_allows_non_overlapping(session: AsyncSession) -> None:
    day = ScheduleDay(date=date(2025, 1, 1))
    session.add(day)
    await session.commit()
    await session.refresh(day)

    await create_schedule_slot(session, day.id, time(9, 0), time(10, 0), 5)
    slot = await create_schedule_slot(session, day.id, time(10, 0), time(11, 0), 3)

    assert slot.capacity == 3
    assert slot.start_time == time(10, 0)
    assert slot.end_time == time(11, 0)


@pytest.mark.asyncio
async def test_create_schedule_slot_blocks_overlap(session: AsyncSession) -> None:
    day = ScheduleDay(date=date(2025, 1, 2))
    session.add(day)
    await session.commit()
    await session.refresh(day)

    await create_schedule_slot(session, day.id, time(9, 0), time(10, 0), 5)

    with pytest.raises(SlotOverlapError):
        await create_schedule_slot(session, day.id, time(9, 30), time(10, 30), 2)
