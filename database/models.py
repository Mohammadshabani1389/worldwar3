from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    default_country_id: Mapped[int | None] = mapped_column(
        ForeignKey("countries.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        index=True,
    )
    is_banned: Mapped[bool] = mapped_column(
        default=False,
        index=True,
    )
    phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ban_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    ban_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Country(Base):
    __tablename__ = "countries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    continent_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chat_type: Mapped[str] = mapped_column(String(32))
    leader_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    leader_name: Mapped[str] = mapped_column(String(255))

    # منابع اولیه
    money: Mapped[float] = mapped_column(Float, default=0.0)
    fuel: Mapped[float] = mapped_column(Float, default=0.0)
    metal: Mapped[float] = mapped_column(Float, default=0.0)
    uranium: Mapped[float] = mapped_column(Float, default=0.0)
    # منابع نامحدود که توسط مدیر قابل فعال/غیرفعال شدن هستند
    infinite_money: Mapped[bool] = mapped_column(default=False)
    infinite_fuel: Mapped[bool] = mapped_column(default=False)
    infinite_metal: Mapped[bool] = mapped_column(default=False)
    infinite_uranium: Mapped[bool] = mapped_column(default=False)

    # ساختمان‌ها
    command_center_level: Mapped[int] = mapped_column(Integer, default=1)
    metal_mine_level: Mapped[int] = mapped_column(Integer, default=0)
    metal_mine_storage: Mapped[float] = mapped_column(Float, default=0.0)
    metal_mine_last_production_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )
    arsenal_level: Mapped[int] = mapped_column(Integer, default=0)
    arsenal_storage: Mapped[float] = mapped_column(Float, default=0.0)
    # زمان پایان ساخت/ارتقای ساختمان‌ها (به UTC)
    command_center_construction_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    command_center_construction_target_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metal_mine_construction_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    metal_mine_construction_target_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    arsenal_construction_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    arsenal_construction_target_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    power_plant_level: Mapped[int] = mapped_column(Integer, default=0)
    bank_level: Mapped[int] = mapped_column(Integer, default=0)
    laboratory_level: Mapped[int] = mapped_column(Integer, default=0)

    # تجهیزات
    defense: Mapped[int] = mapped_column(Integer, default=0)
    drones: Mapped[int] = mapped_column(Integer, default=0)
    missiles: Mapped[int] = mapped_column(Integer, default=0)
    leadership_experience: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )


class UserCountry(Base):
    __tablename__ = "user_countries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        index=True,
    )
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"),
        index=True,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "country_id", name="uq_user_country"),
    )


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )


class BotSetting(Base):
    __tablename__ = "bot_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)


class GroupStatus(Base):
    __tablename__ = "group_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    chat_type: Mapped[str] = mapped_column(String(32), default="group")
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(default=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
