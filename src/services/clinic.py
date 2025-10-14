from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import ClinicProfile

_profile_cache: ClinicProfile | None = None


def _set_cache(profile: ClinicProfile) -> ClinicProfile:
    global _profile_cache
    _profile_cache = profile
    return profile


async def get_profile(session: AsyncSession) -> ClinicProfile:
    profile = await session.get(ClinicProfile, 1)
    if profile:
        return _set_cache(profile)
    profile = ClinicProfile(id=1)
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return _set_cache(profile)


async def get_profile_cached(session: AsyncSession) -> ClinicProfile:
    if _profile_cache is not None:
        return _profile_cache
    return await get_profile(session)


async def update_profile(
    session: AsyncSession,
    *,
    phone_number: Optional[str] = None,
    phone_label: Optional[str] = None,
    address_text: Optional[str] = None,
    location_lat: Optional[float] = None,
    location_lon: Optional[float] = None,
) -> ClinicProfile:
    profile = await get_profile(session)
    if phone_number is not None:
        profile.phone_number = phone_number
    if phone_label is not None:
        profile.phone_label = phone_label
    if address_text is not None:
        profile.address_text = address_text
    if location_lat is not None and location_lon is not None:
        profile.location_lat = location_lat
        profile.location_lon = location_lon
    await session.commit()
    await session.refresh(profile)
    return _set_cache(profile)


async def clear_location(session: AsyncSession) -> ClinicProfile:
    profile = await get_profile(session)
    profile.location_lat = None
    profile.location_lon = None
    await session.commit()
    await session.refresh(profile)
    return _set_cache(profile)
