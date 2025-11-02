# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, Iterable, List

from sqlalchemy import func, select

from src.database import SessionLocal
from src.models import Appointment, Role, User

SEND_DELAY_SECONDS: float = 0.08
_BATCH_SIZE = 500


class _SafeMap(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def chunk_text(text: str, limit: int = 4096) -> List[str]:
    if not text:
        return [""]
    return [text[i : i + limit] for i in range(0, len(text), limit)]


async def db_find_patient_candidates(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    token = (query or "").strip()
    if not token:
        return []
    like_token = f"%{token}%"
    async with SessionLocal() as session:
        stmt = (
            select(
                User.id,
                User.full_name,
                User.national_id,
                User.phone,
                User.tg_id,
            )
            .where(User.role == Role.patient)
            .where(
                func.coalesce(User.national_id, "").ilike(like_token)
                | func.coalesce(User.phone, "").ilike(like_token)
                | func.coalesce(User.full_name, "").ilike(like_token)
            )
            .order_by(func.coalesce(User.full_name, "").asc())
            .limit(limit)
        )
        rows = (await session.execute(stmt)).all()
    results: List[Dict[str, Any]] = []
    for row in rows:
        results.append(
            {
                "id": row.id,
                "name": row.full_name or "-",
                "national_id": row.national_id or "-",
                "phone": row.phone or "-",
                "tg_id": row.tg_id,
            }
        )
    return results

async def db_get_active_patient_ids() -> List[int]:
    async with SessionLocal() as session:
        stmt = select(User.id).where(User.role == Role.patient, User.tg_id.is_not(None))
        rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def db_get_patients_by_ids(ids: Iterable[int]) -> Dict[int, Dict[str, Any]]:
    id_list = list(ids)
    if not id_list:
        return {}
    result: Dict[int, Dict[str, Any]] = {}
    async with SessionLocal() as session:
        for chunk_start in range(0, len(id_list), _BATCH_SIZE):
            chunk = id_list[chunk_start : chunk_start + _BATCH_SIZE]
            stmt = (
                select(
                    User.id,
                    User.full_name,
                    User.phone,
                    User.national_id,
                    User.tg_id,
                )
                .where(User.id.in_(chunk))
            )
            rows = (await session.execute(stmt)).all()
            for row in rows:
                result[row.id] = {
                    "id": row.id,
                    "name": row.full_name or "-",
                    "phone": row.phone or "-",
                    "national_id": row.national_id or "-",
                    "tg_id": row.tg_id,
                }
    return result


async def db_get_last_appointments_for(ids: Iterable[int]) -> Dict[int, Dict[str, Any]]:
    id_list = list(ids)
    if not id_list:
        return {}
    async with SessionLocal() as session:
        windowed = select(
            Appointment.user_id,
            Appointment.id.label("appointment_id"),
            Appointment.jdate,
            Appointment.time_slot,
            Appointment.status,
            Appointment.created_at,
            func.row_number()
            .over(
                partition_by=Appointment.user_id,
                order_by=(
                    Appointment.jdate.desc(),
                    Appointment.time_slot.desc(),
                    Appointment.id.desc(),
                ),
            )
            .label("rnum"),
        ).where(Appointment.user_id.in_(id_list)).subquery()
        stmt = select(windowed).where(windowed.c.rnum == 1)
        rows = (await session.execute(stmt)).all()
    last_map: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        last_map[row.user_id] = {
            "id": row.appointment_id,
            "date": row.jdate,
            "time": row.time_slot,
            "status": row.status.value if hasattr(row.status, "value") else row.status,
        }
    return last_map


def render_patient_template(template: str, patient: Dict[str, Any], last_appt: Dict[str, Any] | None) -> str:
    ctx = {
        "name": patient.get("name") or "-",
        "phone": patient.get("phone") or "-",
        "national_id": patient.get("national_id") or "-",
        "date": (last_appt or {}).get("date") or "-",
        "time": (last_appt or {}).get("time") or "-",
        "appointment_id": (last_appt or {}).get("id") or "-",
        "status": (last_appt or {}).get("status") or "-",
    }
    return template.format_map(_SafeMap(ctx))



