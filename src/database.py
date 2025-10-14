import asyncpg
from asyncpg.exceptions import DuplicateDatabaseError, InvalidCatalogNameError
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from src.config import settings

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

class Base(AsyncAttrs, DeclarativeBase):
    pass

async def init_db():
    from src import models
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await _ensure_optional_columns(conn)
    except InvalidCatalogNameError:
        await _create_database()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await _ensure_optional_columns(conn)


async def _create_database() -> None:
    url = make_url(settings.database_url)
    db_name = url.database
    if not db_name:
        raise ValueError("Database name missing in DATABASE_URL")
    admin_url = url.set(database="postgres")
    admin_dsn = admin_url.render_as_string(hide_password=False).replace("+asyncpg", "")
    conn = await asyncpg.connect(admin_dsn)
    try:
        await conn.execute(f'CREATE DATABASE "{db_name}"')
    except DuplicateDatabaseError:
        pass
    finally:
        await conn.close()

async def _ensure_optional_columns(conn) -> None:
    await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS birth_date DATE"))
    await conn.execute(text("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS slot_id INTEGER"))
    await conn.execute(text("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS payment_status paymentstatus DEFAULT 'unpaid'"))
    await conn.execute(text("UPDATE appointments SET payment_status = 'unpaid' WHERE payment_status IS NULL"))
    await conn.execute(text("ALTER TABLE appointments ALTER COLUMN payment_status SET NOT NULL"))
    await conn.execute(text("CREATE TABLE IF NOT EXISTS clinic_profile (id INTEGER PRIMARY KEY, phone_number VARCHAR(32), phone_label VARCHAR(64), address_text TEXT, location_lat DOUBLE PRECISION, location_lon DOUBLE PRECISION, updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW())"))
    await conn.execute(text("INSERT INTO clinic_profile (id, updated_at) VALUES (1, NOW()) ON CONFLICT (id) DO NOTHING"))
    await conn.execute(text("ALTER TABLE clinic_profile ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITHOUT TIME ZONE"))
    await conn.execute(text("UPDATE clinic_profile SET updated_at = NOW() WHERE updated_at IS NULL"))
    await conn.execute(text("ALTER TABLE clinic_profile ALTER COLUMN updated_at SET DEFAULT NOW()"))
    await conn.execute(text("ALTER TABLE clinic_profile ALTER COLUMN updated_at SET NOT NULL"))
    await conn.execute(text("CREATE TABLE IF NOT EXISTS online_consult_requests (id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, question TEXT NOT NULL, receipt_file_id VARCHAR(256), status onlineconsultrequeststatus DEFAULT 'pending' NOT NULL, admin_notes TEXT, answer TEXT, created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(), updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW())"))
