# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from sqlalchemy import select

from src.database import SessionLocal
from src.models import Role, User
from src.utils.validation import to_english_digits


async def db_find_patient_by_national_id(national_id: str) -> Optional[Dict[str, Any]]:
    if not national_id:
        return None
    normalized = to_english_digits(national_id)
    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(User.national_id == normalized, User.role == Role.patient)
        )
        user = result.scalar_one_or_none()
        if not user:
            return None
        return _serialize_user(user)


async def db_patient_exists(national_id: str) -> bool:
    return (await db_find_patient_by_national_id(national_id)) is not None


async def db_upsert_patient(data: Dict[str, Any], *, update_existing: bool) -> int:
    payload = dict(data)
    payload.pop("pending_update", None)

    national_id = to_english_digits(payload.get("national_id", "")).strip()
    if not national_id:
        raise ValueError("national_id is required for patient upsert")

    async with SessionLocal() as session:
        user: User | None = None
        if update_existing:
            existing_id = payload.get("existing_id")
            if existing_id:
                user = await session.get(User, existing_id)
            if not user:
                result = await session.execute(
                    select(User).where(User.national_id == national_id, User.role == Role.patient)
                )
                user = result.scalar_one_or_none()
        if user is None:
            user = User(
                national_id=national_id,
                role=Role.patient,
            )
            session.add(user)

        user.full_name = payload.get("name") or user.full_name
        user.phone = payload.get("phone") or user.phone
        user.tg_id = payload.get("tg_id") or user.tg_id
        birthdate = payload.get("birthdate")
        if isinstance(birthdate, str):
            birthdate = None
        if birthdate is not None:
            user.birth_date = birthdate
        if payload.get("gender") is not None:
            user.gender = payload.get("gender")
        if payload.get("insurance") is not None:
            user.insurance = payload.get("insurance")
        if payload.get("address") is not None:
            user.address = payload.get("address")
        user.is_active = True if payload.get("is_active") is None else bool(payload.get("is_active"))

        await session.commit()
        await session.refresh(user)
        return user.id


def _serialize_user(user: User) -> Dict[str, Any]:
    return {
        "id": user.id,
        "tg_id": user.tg_id,
        "name": user.full_name or "",
        "national_id": user.national_id or "",
        "phone": user.phone or "",
        "birthdate": user.birth_date,
        "gender": user.gender or None,
        "insurance": user.insurance or None,
        "address": user.address or None,
        "is_active": user.is_active,
    }
