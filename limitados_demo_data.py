from __future__ import annotations

import random
import secrets
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from fut7.models import Match, MatchRoster, PlayerStats, Rating, Team, User
from fut7.security import hash_password

DEMO_MARKER = "DEMO_LIMITADOS_V1"
DEMO_PLAYERS = (
    ("Rafael Nogueira", "GOL"),
    ("Bruno Azevedo", "ZAG"),
    ("Caio Menezes", "ZAG"),
    ("Davi Peixoto", "ZAG"),
    ("Enzo Duarte", "ALA"),
    ("Gabriel Lacerda", "ALA"),
    ("Henrique Valença", "MEI"),
    ("Igor Barcelos", "MEI"),
    ("Lucas Falcão", "MEI"),
    ("Matheus Gouveia", "ATA"),
)
DEMO_MATCHES = (
    ("Estrelas da Serra", date(2026, 9, 5), 2, 1),
    ("Vento Norte FC", date(2026, 9, 12), 3, 2),
    ("Bola de Ouro", date(2026, 9, 19), 1, 1),
    ("Atlético do Parque", date(2026, 9, 26), 4, 0),
    ("União Central", date(2026, 10, 3), 2, 3),
    ("Fênix do Vale", date(2026, 10, 10), 3, 1),
)


def _demo_email(name: str) -> str:
    slug = name.casefold().replace(" ", ".")
    return f"{slug}@limitados.demo.invalid"


def _ensure_demo_players(db: Session, team: Team) -> list[User]:
    players = list(db.scalars(
        select(User)
        .where(User.team_id == team.id, User.role == "player", User.active.is_(True))
        .order_by(User.id)
    ))
    by_email = {player.email.casefold(): player for player in players}
    for name, position in DEMO_PLAYERS:
        email = _demo_email(name)
        player = by_email.get(email)
        if player is None:
            player = db.scalar(select(User).where(User.email == email))
            if player is not None and player.team_id != team.id:
                raise ValueError(f"O e-mail de demonstração {email} já pertence a outro time.")
        if player is None:
            player = User(
                name=name,
                email=email,
                password_hash=hash_password(secrets.token_urlsafe(32)),
                role="player",
                team_id=team.id,
                height_cm=170 + len(players) % 18,
                weight_kg=65 + len(players) % 16,
                preferred_foot="Direito" if len(players) % 2 == 0 else "Esquerdo",
                primary_position=position,
                active=True,
            )
            db.add(player)
            db.flush()
        by_email[email] = player
        if player not in players:
            players.append(player)
    return players


def _lineup(players: list[User], round_index: int) -> list[tuple[User, bool]]:
    by_position: dict[str, list[User]] = {"GOL": [], "ZAG": [], "MID": [], "ATA": []}
    for player in players:
        position = player.primary_position or "MEI"
        group = "MID" if position in {"ALA", "MEI"} else position
        if group in by_position:
            by_position[group].append(player)

    starters: list[User] = []
    starters.extend(by_position["GOL"][:1])
    for group, count in (("ZAG", 2), ("MID", 3), ("ATA", 1)):
        candidates = by_position[group]
        if not candidates:
            raise ValueError(f"O time Limitados não tem jogadores disponíveis para a posição {group}.")
        offset = round_index % len(candidates)
        rotated = candidates[offset:] + candidates[:offset]
        starters.extend(rotated[:count])
    remaining = [player for player in players if player not in starters]
    reserve_offset = round_index % len(remaining) if remaining else 0
    reserves = (remaining[reserve_offset:] + remaining[:reserve_offset])[:2]
    return [(player, True) for player in starters] + [(player, False) for player in reserves]


def _record_match(
    db: Session,
    team: Team,
    players: list[User],
    opponent: str,
    played_on: date,
    score_for: int,
    score_against: int,
    round_index: int,
) -> Match:
    marker = f"{DEMO_MARKER}: RODADA {round_index + 1:02d}"
    match = db.scalar(select(Match).where(Match.team_id == team.id, Match.notes == marker))
    if match is not None:
        return match

    match = Match(
        team_id=team.id,
        opponent=opponent,
        played_on=played_on,
        venue="Arena Limitados (campo fictício)",
        formation="2-3-1",
        status="played",
        home_score=score_for,
        away_score=score_against,
        notes=marker,
    )
    db.add(match)
    db.flush()
    lineup = _lineup(players, round_index)
    participating = [player for player, _ in lineup]
    for slot, (player, is_starter) in enumerate(lineup):
        position = player.primary_position or "MEI"
        db.add(MatchRoster(
            match_id=match.id,
            player_id=player.id,
            position=position,
            slot=slot,
            is_starter=is_starter,
        ))

    rng = random.Random(20261031 + round_index)
    match_stats = {
        player.id: {
            "goals": 0,
            "assists": 0,
            "shots_on_target": rng.randint(0, 2),
            "tackles": rng.randint(0, 4),
        }
        for player in participating
    }
    scorers = [player for player in participating if player.primary_position == "ATA"]
    scorers += [player for player in participating if player.primary_position in {"ALA", "MEI"}]
    for goal_index in range(score_for):
        scorer = scorers[(goal_index + round_index) % len(scorers)]
        match_stats[scorer.id]["goals"] += 1
        match_stats[scorer.id]["shots_on_target"] += 1
        if goal_index % 3 != 2:
            assistants = [player for player in participating if player.id != scorer.id]
            assistant = assistants[(goal_index + round_index * 2) % len(assistants)]
            match_stats[assistant.id]["assists"] += 1
    for player in participating:
        db.add(PlayerStats(
            match_id=match.id,
            player_id=player.id,
            coach_rating=round(3.2 + ((player.id + round_index) % 18) / 10, 1),
            **match_stats[player.id],
        ))

    for rater in participating:
        for rated in participating:
            if rater.id == rated.id:
                continue
            score = 3.0 + ((rater.id * 3 + rated.id + round_index) % 21) / 10
            db.add(Rating(
                match_id=match.id,
                rater_id=rater.id,
                rated_player_id=rated.id,
                score=min(5.0, score),
            ))
    return match


def seed_limitados_demo(db: Session) -> dict[str, int | str]:
    team = db.scalar(select(Team).where(Team.name_key == "limitados"))
    if team is None:
        raise ValueError("O time Limitados não foi encontrado no banco atual.")
    players = _ensure_demo_players(db, team)
    matches = [
        _record_match(db, team, players, opponent, played_on, score_for, score_against, index)
        for index, (opponent, played_on, score_for, score_against) in enumerate(DEMO_MATCHES)
    ]
    db.flush()
    return {
        "team": team.name,
        "players": len(players),
        "matches": len(matches),
        "goals_for": sum(match.home_score or 0 for match in matches),
        "goals_against": sum(match.away_score or 0 for match in matches),
    }


def main() -> None:
    from fut7.database import SessionLocal, init_db

    init_db()
    with SessionLocal.begin() as db:
        summary = seed_limitados_demo(db)
    print(
        f"Dados de demonstração atualizados para {summary['team']}: "
        f"{summary['players']} jogadores, {summary['matches']} partidas, "
        f"{summary['goals_for']} gols marcados e {summary['goals_against']} sofridos."
    )


if __name__ == "__main__":
    main()
