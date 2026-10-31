from __future__ import annotations

from collections.abc import Iterable
from statistics import mean

from fut7.models import PlayerStats, Rating, User

ATTRIBUTE_LABELS = {
    "Ataque": "ATA",
    "Defesa": "DEF",
    "Força": "FOR",
    "Velocidade": "VEL",
    "Técnica": "TEC",
    "Inteligência": "INT",
}


def _bounded_score(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def calculate_attributes(
    player: User,
    stats: Iterable[PlayerStats],
    peer_ratings: Iterable[Rating],
) -> dict[str, float]:
    """Derive six explainable 0–100 attributes from profile and per-match history."""
    stat_rows = list(stats)
    ratings = list(peer_ratings)
    appearances = max(1, len(stat_rows))
    goals_pg = sum(row.goals for row in stat_rows) / appearances
    assists_pg = sum(row.assists for row in stat_rows) / appearances
    shots_pg = sum(row.shots_on_target for row in stat_rows) / appearances
    tackles_pg = sum(row.tackles for row in stat_rows) / appearances
    discipline_pg = sum(row.yellow_cards + 2 * row.red_cards for row in stat_rows) / appearances
    coach_ratings = [row.coach_rating for row in stat_rows if row.coach_rating is not None]
    coach_rating = mean(coach_ratings) if coach_ratings else 2.5
    team_rating = mean([rating.score for rating in ratings]) if ratings else 2.5
    performance = (coach_rating + team_rating) / 2 * 20

    height = player.height_cm or 170
    weight = player.weight_kg or 70
    bmi = weight / ((height / 100) ** 2)
    strength_profile = 100 - min(abs(bmi - 24) * 5, 40)
    speed_profile = 100 - min(max(height - 170, 0) * 0.35 + max(18.5 - bmi, 0) * 2, 35)

    return {
        "Ataque": _bounded_score(35 + min(goals_pg, 2) * 20 + min(assists_pg, 2) * 10 + min(shots_pg, 4) * 5 + performance * 0.1),
        "Defesa": _bounded_score(35 + min(tackles_pg, 6) * 7 + performance * 0.15 - discipline_pg * 5),
        "Força": _bounded_score(strength_profile * 0.55 + performance * 0.25 + min(tackles_pg, 5) * 4),
        "Velocidade": _bounded_score(speed_profile * 0.65 + min(shots_pg + assists_pg, 5) * 5 + performance * 0.1),
        "Técnica": _bounded_score(30 + min(assists_pg, 2) * 15 + min(shots_pg, 4) * 8 + performance * 0.2),
        "Inteligência": _bounded_score(25 + performance * 0.45 + min(assists_pg, 3) * 8 + min(tackles_pg, 5) * 3),
    }


def calculate_final_rating(coach_rating: float | None, peer_ratings: Iterable[Rating]) -> float | None:
    peer_scores = [rating.score for rating in peer_ratings]
    if coach_rating is None or not peer_scores:
        return None
    return round((mean(peer_scores) + coach_rating) / 2, 2)


def overall_from_attributes(attributes: dict[str, float]) -> int:
    return round(mean(attributes.values())) if attributes else 0
