from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models import ClinicProfile

_profile_cache: ClinicProfile | None = None


def invalidate_profile_cache() -> None:
    global _profile_cache
    _profile_cache = None


def _set_cache(profile: ClinicProfile) -> ClinicProfile:
    global _profile_cache
    _profile_cache = profile
    return profile


def _ensure_manual_defaults(profile: ClinicProfile, *, created: bool = False) -> bool:
    changed = created

    def apply(attr: str, value):
        nonlocal changed
        if value is None:
            return
        if getattr(profile, attr) != value:
            setattr(profile, attr, value)
            changed = True

    apply("phone_number", settings.clinic_phone_number)
    apply("phone_label", settings.clinic_phone_label)
    apply("address_text", settings.clinic_address_text)

    lat = settings.clinic_location_lat
    lon = settings.clinic_location_lon
    if lat is not None and lon is not None:
        if profile.location_lat != lat or profile.location_lon != lon:
            profile.location_lat = lat
            profile.location_lon = lon
            changed = True
    return changed


async def get_profile(session: AsyncSession) -> ClinicProfile:
    profile = await session.get(ClinicProfile, 1)
    created = False
    if profile is None:
        profile = ClinicProfile(id=1)
        session.add(profile)
        created = True
    if _ensure_manual_defaults(profile, created=created):
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
