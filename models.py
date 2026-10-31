from __future__ import annotations

from datetime import date, datetime, time, timezone

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("name_key", name="uq_team_name_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    name_key: Mapped[str] = mapped_column(String(120), nullable=False)
    invite_pin_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    logo_data: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow_naive, nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="player")
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    height_cm: Mapped[int | None] = mapped_column(Integer)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    preferred_foot: Mapped[str | None] = mapped_column(String(20))
    primary_position: Mapped[str | None] = mapped_column(String(20))
    secondary_position: Mapped[str | None] = mapped_column(String(20))
    photo_url: Mapped[str | None] = mapped_column(String(500))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow_naive, nullable=False)

    stats: Mapped[list[PlayerStats]] = relationship(back_populates="player")
    goals: Mapped[list[Goal]] = relationship(back_populates="player")


class WebSession(Base):
    __tablename__ = "web_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow_naive, nullable=False)


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    opponent: Mapped[str] = mapped_column(String(100), nullable=False)
    played_on: Mapped[date] = mapped_column(Date, nullable=False)
    kickoff_time: Mapped[time | None] = mapped_column(Time)
    venue: Mapped[str | None] = mapped_column(String(150))
    formation: Mapped[str] = mapped_column(String(30), default="2-3-1", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="scheduled", nullable=False)
    home_score: Mapped[int | None] = mapped_column(Integer)
    away_score: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow_naive, nullable=False)

    roster: Mapped[list[MatchRoster]] = relationship(back_populates="match", cascade="all, delete-orphan")
    stats: Mapped[list[PlayerStats]] = relationship(back_populates="match", cascade="all, delete-orphan")
    goals: Mapped[list[Goal]] = relationship(back_populates="match", cascade="all, delete-orphan")
    ratings: Mapped[list[Rating]] = relationship(back_populates="match", cascade="all, delete-orphan")


class MatchRoster(Base):
    __tablename__ = "match_roster"
    __table_args__ = (UniqueConstraint("match_id", "player_id", name="uq_roster_match_player"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    position: Mapped[str] = mapped_column(String(20), default="MEI", nullable=False)
    slot: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_starter: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    field_x: Mapped[float | None] = mapped_column(Float)
    field_y: Mapped[float | None] = mapped_column(Float)

    match: Mapped[Match] = relationship(back_populates="roster")
    player: Mapped[User] = relationship()


class PlayerStats(Base):
    __tablename__ = "player_stats"
    __table_args__ = (UniqueConstraint("match_id", "player_id", name="uq_stats_match_player"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    goals: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    assists: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shots_on_target: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tackles: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    yellow_cards: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    red_cards: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    coach_rating: Mapped[float | None] = mapped_column(Float)

    match: Mapped[Match] = relationship(back_populates="stats")
    player: Mapped[User] = relationship(back_populates="stats")


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
    player_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    description: Mapped[str] = mapped_column(String(250), nullable=False)
    target_value: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow_naive, nullable=False)

    match: Mapped[Match | None] = relationship(back_populates="goals")
    player: Mapped[User] = relationship(back_populates="goals")


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (
        UniqueConstraint("match_id", "rater_id", "rated_player_id", name="uq_rating_once_per_match"),
        CheckConstraint("score >= 0 AND score <= 5", name="ck_rating_score_range"),
        CheckConstraint("rater_id <> rated_player_id", name="ck_rating_not_self"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), nullable=False)
    rater_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    rated_player_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow_naive, nullable=False)

    match: Mapped[Match] = relationship(back_populates="ratings")
