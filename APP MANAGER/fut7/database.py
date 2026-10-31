from __future__ import annotations

import os
import secrets
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.orm import sessionmaker

from fut7.models import Base, Team, User
from fut7.security import hash_password, normalize_team_name


def _database_url() -> str:
    configured = os.getenv("FUT7_DATABASE_URL")
    if configured:
        return configured
    data_dir = Path(os.getenv("FUT7_DATA_DIR", "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(data_dir / 'fut7.db').resolve().as_posix()}"


DATABASE_URL = _database_url()
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})

if engine.dialect.name == "sqlite":
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(connection, _) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _migrate_existing_database()


def _migrate_existing_database() -> None:
    obsolete_season_tables = (
        "season_player_match_stats",
        "season_matches",
        "season_players",
        "season_clubs",
        "sports_seasons",
    )
    table_columns = {
        table_name: {column["name"] for column in inspect(engine).get_columns(table_name)}
        for table_name in ("teams", "users", "matches", "match_roster")
    }
    with engine.begin() as connection:
        existing_tables = set(inspect(connection).get_table_names())
        for table_name in obsolete_season_tables:
            if table_name in existing_tables:
                connection.execute(text(f"DROP TABLE {table_name}"))
        for table_name, columns in table_columns.items():
            if table_name in ("users", "matches") and "team_id" not in columns:
                connection.execute(text(
                    f"ALTER TABLE {table_name} ADD COLUMN team_id INTEGER REFERENCES teams(id)"
                ))
            if table_name == "teams" and "logo_data" not in columns:
                connection.execute(text("ALTER TABLE teams ADD COLUMN logo_data TEXT"))
            if table_name == "users" and "secondary_position" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN secondary_position VARCHAR(20)"))
            if table_name == "matches" and "home_score" not in columns:
                connection.execute(text("ALTER TABLE matches ADD COLUMN home_score INTEGER"))
            if table_name == "matches" and "away_score" not in columns:
                connection.execute(text("ALTER TABLE matches ADD COLUMN away_score INTEGER"))
            if table_name == "matches" and "kickoff_time" not in columns:
                connection.execute(text("ALTER TABLE matches ADD COLUMN kickoff_time TIME"))
            if table_name == "match_roster" and "field_x" not in columns:
                connection.execute(text("ALTER TABLE match_roster ADD COLUMN field_x FLOAT"))
            if table_name == "match_roster" and "field_y" not in columns:
                connection.execute(text("ALTER TABLE match_roster ADD COLUMN field_y FLOAT"))

    with SessionLocal.begin() as db:
        for coach in db.scalars(select(User).where(User.role == "coach", User.team_id.is_(None))):
            base_name = f"{coach.name.strip() or 'Meu time'} FC"
            team_name = base_name[:100]
            team_key = normalize_team_name(team_name)
            if db.scalar(select(Team.id).where(Team.name_key == team_key)) is not None:
                suffix = f" {coach.id}"
                team_name = f"{base_name[:100 - len(suffix)]}{suffix}"
                team_key = normalize_team_name(team_name)
            team = Team(
                name=team_name,
                name_key=team_key,
                invite_pin_hash=hash_password(f"{secrets.randbelow(900_000) + 100_000}"),
            )
            db.add(team)
            db.flush()
            coach.team_id = team.id

        teams = list(db.scalars(select(Team).order_by(Team.id)))
        if len(teams) == 1:
            legacy_team_id = teams[0].id
            db.execute(
                text("UPDATE users SET team_id = :team_id WHERE team_id IS NULL"),
                {"team_id": legacy_team_id},
            )
            db.execute(
                text("UPDATE matches SET team_id = :team_id WHERE team_id IS NULL"),
                {"team_id": legacy_team_id},
            )
