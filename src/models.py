from sqlalchemy import (
    String,
    Integer,
    ForeignKey,
    Date,
    Time,
    DateTime,
    Enum,
    Text,
    BigInteger,
    Boolean,
    Float,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, date, time
import enum
from src.database import Base

class Role(str, enum.Enum):
    patient = "patient"
    admin = "admin"

class AppointmentStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    canceled = "canceled"

class PaymentStatus(str, enum.Enum):
    unpaid = "unpaid"
    awaiting_confirmation = "awaiting_confirmation"
    settled = "settled"
    rejected = "rejected"

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    national_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.patient, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    appointments: Mapped[list["Appointment"]] = relationship(back_populates="user")

class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    jdate: Mapped[str] = mapped_column(String(16), index=True)  # e.g. 1403-12-20
    time_slot: Mapped[str] = mapped_column(String(16))          # e.g. 10:30
    status: Mapped[AppointmentStatus] = mapped_column(Enum(AppointmentStatus), default=AppointmentStatus.pending)
    receipt_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus), default=PaymentStatus.unpaid, nullable=False)
    slot_id: Mapped[int | None] = mapped_column(ForeignKey("schedule_slots.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="appointments")
    slot: Mapped["ScheduleSlot"] = relationship(back_populates="appointments")

class Consultation(Base):
    __tablename__ = "clinic_consultations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class OnlineConsultRequestStatus(str, enum.Enum):
    pending = "pending"
    awaiting_confirmation = "awaiting_confirmation"
    approved = "approved"
    rejected = "rejected"
    completed = "completed"

class OnlineConsultRequest(Base):
    __tablename__ = "online_consult_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text)
    receipt_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[OnlineConsultRequestStatus] = mapped_column(
        Enum(OnlineConsultRequestStatus), default=OnlineConsultRequestStatus.pending, nullable=False
    )
    admin_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ClinicProfile(Base):
    __tablename__ = "clinic_profile"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    phone_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    address_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ScheduleDay(Base):
    __tablename__ = "schedule_days"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    slots: Mapped[list["ScheduleSlot"]] = relationship(
        back_populates="day",
        cascade="all, delete-orphan",
        order_by="ScheduleSlot.start_time",
    )

class ScheduleSlot(Base):
    __tablename__ = "schedule_slots"
    __table_args__ = (UniqueConstraint("day_id", "start_time", "end_time", name="uq_schedule_slot_time"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    day_id: Mapped[int] = mapped_column(ForeignKey("schedule_days.id", ondelete="CASCADE"))
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    day: Mapped[ScheduleDay] = relationship(back_populates="slots")
    appointments: Mapped[list[Appointment]] = relationship(back_populates="slot")

    @property
    def label(self) -> str:
        start = self.start_time.strftime("%H:%M")
        end = self.end_time.strftime("%H:%M")
        return f"{start} - {end}"
