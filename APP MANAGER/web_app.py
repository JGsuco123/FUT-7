from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from fut7.database import SessionLocal, init_db
from fut7.logic import calculate_attributes, overall_from_attributes
from fut7.models import Match, MatchRoster, PlayerStats, Rating, Team, User, WebSession
from fut7.registration import logo_data_from_upload, valid_email_address
from fut7.security import (
    hash_password,
    is_valid_invite_pin,
    normalize_team_name,
    verify_password,
)

SESSION_COOKIE = "fut7_session"
SESSION_TTL = timedelta(days=14)
MAX_REQUEST_BYTES = 3 * 1024 * 1024
POSITION_OPTIONS = {"GOL", "ZAG", "ALA", "MEI", "ATA"}
FORMATION_OPTIONS = {"Livre", "2-3-1", "3-2-1", "2-2-2", "1-3-2"}
ATTRIBUTE_ORDER = ("Ataque", "Defesa", "Força", "Velocidade", "Técnica", "Inteligência")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class APIError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code


def _json_error(error: APIError) -> JSONResponse:
    return JSONResponse({"error": error.message}, status_code=error.status_code)


async def _payload(request: Request) -> dict:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError as error:
            raise APIError("Cabeçalho de tamanho inválido.", 400) from error
        if declared_length < 0 or declared_length > MAX_REQUEST_BYTES:
            raise APIError("O envio excede o limite permitido.", 413)
    body = await request.body()
    if len(body) > MAX_REQUEST_BYTES:
        raise APIError("O envio excede o limite permitido.", 413)
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise APIError("Envie um corpo JSON válido.") from error
    if not isinstance(payload, dict):
        raise APIError("O corpo da solicitação deve ser um objeto JSON.")
    return payload


def _required_text(payload: dict, key: str, label: str, maximum: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise APIError(f"Informe {label} (até {maximum} caracteres).", 422)
    return value.strip()


def _check_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    parsed = urlsplit(origin)
    if parsed.netloc != request.url.netloc or parsed.scheme not in {"http", "https"}:
        raise APIError("Origem da solicitação não autorizada.", 403)


def _new_session(db, user: User, response: Response) -> None:
    now = _utcnow()
    db.execute(delete(WebSession).where(WebSession.expires_at <= now))
    token = secrets.token_urlsafe(32)
    db.add(WebSession(
        user_id=user.id,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        expires_at=now + SESSION_TTL,
    ))
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=os.getenv("FUT7_COOKIE_SECURE", "").casefold() in {"1", "true", "yes"},
        samesite="lax",
        path="/",
    )


def _current_user(request: Request, db) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise APIError("Entre na sua conta para continuar.", 401)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    web_session = db.scalar(select(WebSession).where(
        WebSession.token_hash == token_hash,
        WebSession.expires_at > _utcnow(),
    ))
    user = db.get(User, web_session.user_id) if web_session else None
    if not user or not user.active:
        raise APIError("Sua sessão expirou. Entre novamente.", 401)
    return user


def _coach(user: User) -> None:
    if user.role != "coach":
        raise APIError("Somente o treinador pode realizar esta ação.", 403)


def _account_payload(db, user: User) -> dict:
    team = db.get(Team, user.team_id)
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "team": {"id": team.id, "name": team.name, "logo": team.logo_data},
        "player": _player_payload(db, user, include_details=True, include_profile=True) if user.role == "player" else None,
    }


def _player_payload(
    db,
    player: User,
    *,
    include_details: bool = False,
    include_profile: bool = False,
) -> dict:
    stats = list(db.scalars(select(PlayerStats).where(PlayerStats.player_id == player.id)))
    ratings = list(db.scalars(select(Rating).where(Rating.rated_player_id == player.id)))
    attributes = calculate_attributes(player, stats, ratings)
    values = [round(attributes[label]) for label in ATTRIBUTE_ORDER]
    result = {
        "id": player.id,
        "name": player.name,
        "position": player.primary_position or "MEI",
        "photo_url": player.photo_url,
        "attributes": values,
        "overall": overall_from_attributes(attributes),
    }
    if include_details:
        coach_ratings = [row.coach_rating for row in stats if row.coach_rating is not None]
        peer_scores = [row.score for row in ratings]
        result["stats"] = {
            "games": len(stats),
            "goals": sum(row.goals for row in stats),
            "assists": sum(row.assists for row in stats),
            "tackles": sum(row.tackles for row in stats),
            "yellow_cards": sum(row.yellow_cards for row in stats),
            "red_cards": sum(row.red_cards for row in stats),
            "coach_rating": round(sum(coach_ratings) / len(coach_ratings), 2) if coach_ratings else None,
            "peer_rating": round(sum(peer_scores) / len(peer_scores), 2) if peer_scores else None,
        }
    if include_profile:
        result.update({
            "secondary_position": player.secondary_position,
            "height_cm": player.height_cm,
            "weight_kg": player.weight_kg,
            "preferred_foot": player.preferred_foot,
        })
    return result


def _match_payload(db, match: Match) -> dict:
    roster = list(db.scalars(
        select(MatchRoster)
        .join(User, MatchRoster.player_id == User.id)
        .where(MatchRoster.match_id == match.id)
        .order_by(MatchRoster.slot, User.name)
    ))
    stats_by_player = {
        row.player_id: row
        for row in db.scalars(select(PlayerStats).where(PlayerStats.match_id == match.id))
    }
    return {
        "id": match.id,
        "opponent": match.opponent,
        "played_on": match.played_on.isoformat(),
        "kickoff_time": match.kickoff_time.isoformat(timespec="minutes") if match.kickoff_time else "",
        "venue": match.venue or "",
        "formation": match.formation,
        "status": match.status,
        "home_score": match.home_score,
        "away_score": match.away_score,
        "roster": [
            {
                **_player_payload(db, item.player),
                "roster_position": item.position,
                "slot": item.slot,
                "is_starter": item.is_starter,
                "field_x": item.field_x,
                "field_y": item.field_y,
                "match_stats": {
                    "goals": stats_by_player[item.player_id].goals if item.player_id in stats_by_player else 0,
                    "assists": stats_by_player[item.player_id].assists if item.player_id in stats_by_player else 0,
                    "yellow_cards": stats_by_player[item.player_id].yellow_cards if item.player_id in stats_by_player else 0,
                    "red_cards": stats_by_player[item.player_id].red_cards if item.player_id in stats_by_player else 0,
                },
            }
            for item in roster
        ],
    }


def _team_matches(db, team_id: int) -> list[Match]:
    return list(db.scalars(
        select(Match).where(Match.team_id == team_id)
        .order_by(Match.played_on.desc(), Match.kickoff_time.desc(), Match.id.desc())
    ))


def _decode_logo(data_url: object) -> str | None:
    if data_url in (None, ""):
        return None
    if not isinstance(data_url, str) or len(data_url) > MAX_REQUEST_BYTES:
        raise APIError("O arquivo do escudo excede o limite permitido.", 413)
    header, separator, encoded = data_url.partition(",")
    if not separator or header not in {
        "data:image/png;base64",
        "data:image/jpeg;base64",
        "data:image/webp;base64",
    }:
        raise APIError("Envie um escudo em PNG, JPEG ou WebP.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise APIError("O arquivo do escudo está inválido.") from error

    class UploadedLogo:
        def getvalue(self) -> bytes:
            return raw

    try:
        return logo_data_from_upload(UploadedLogo())
    except ValueError as error:
        raise APIError(str(error), 422) from error


def _validate_roster(db, team_id: int, payload: dict) -> list[dict]:
    formation = payload.get("formation", "Livre")
    if not isinstance(formation, str) or formation not in FORMATION_OPTIONS:
        raise APIError("Escolha uma formação tática válida.", 422)
    entries = payload.get("roster")
    if not isinstance(entries, list):
        raise APIError("Informe a escalação da partida.", 422)

    normalized = []
    seen_ids: set[int] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise APIError("Há um jogador inválido na escalação.", 422)
        player_id = entry.get("player_id")
        position = entry.get("position")
        is_starter = entry.get("is_starter")
        if not isinstance(player_id, int) or isinstance(player_id, bool) or player_id <= 0 or player_id in seen_ids:
            raise APIError("Cada atleta deve aparecer uma única vez na escalação.", 422)
        if position is None:
            position = ""
        if not isinstance(position, str) or position not in POSITION_OPTIONS | {""} or not isinstance(is_starter, bool):
            raise APIError("Confira posição e função dos atletas convocados.", 422)
        field_x = entry.get("field_x")
        field_y = entry.get("field_y")
        if (field_x is None) != (field_y is None):
            raise APIError("Informe as duas coordenadas do atleta no campo.", 422)
        if field_x is not None:
            if (
                not is_starter
                or not isinstance(field_x, (int, float))
                or isinstance(field_x, bool)
                or not math.isfinite(field_x)
                or not 0 <= field_x <= 100
                or not isinstance(field_y, (int, float))
                or isinstance(field_y, bool)
                or not math.isfinite(field_y)
                or not 0 <= field_y <= 100
            ):
                raise APIError("As posições no campo devem estar entre 0 e 100.", 422)
        seen_ids.add(player_id)
        normalized.append({
            "player_id": player_id,
            "position": position,
            "is_starter": is_starter,
            "field_x": float(field_x) if field_x is not None else None,
            "field_y": float(field_y) if field_y is not None else None,
        })
    if seen_ids:
        valid_ids = set(db.scalars(
            select(User.id).where(
                User.id.in_(seen_ids),
                User.team_id == team_id,
                User.role == "player",
                User.active.is_(True),
            )
        ))
        if valid_ids != seen_ids:
            raise APIError("A escalação contém atleta inativo ou de outro time.", 422)
    return normalized


async def list_teams(request: Request) -> Response:
    del request
    with SessionLocal() as db:
        teams = list(db.scalars(select(Team).order_by(Team.name)))
        return JSONResponse([
            {"id": team.id, "name": team.name, "logo": team.logo_data}
            for team in teams
        ])


async def register_coach(request: Request) -> Response:
    _check_same_origin(request)
    payload = await _payload(request)
    name = _required_text(payload, "name", "o nome do treinador", 100)
    email = _required_text(payload, "email", "um e-mail", 255).lower()
    password = payload.get("password")
    team_name = _required_text(payload, "team_name", "o nome do time", 100)
    pin = payload.get("pin")
    if not valid_email_address(email):
        raise APIError("Informe um e-mail válido.", 422)
    if not isinstance(password, str) or len(password) < 8 or len(password) > 128:
        raise APIError("A senha deve conter entre 8 e 128 caracteres.", 422)
    if not isinstance(pin, str) or not is_valid_invite_pin(pin):
        raise APIError("O PIN deve conter de 6 a 12 dígitos numéricos.", 422)
    logo_data = _decode_logo(payload.get("logo"))
    password_hash = await run_in_threadpool(hash_password, password)

    response = JSONResponse({})
    try:
        with SessionLocal.begin() as db:
            if db.scalar(select(User.id).where(User.email == email)):
                raise APIError("Este e-mail já está cadastrado.", 409)
            team_key = normalize_team_name(team_name)
            if db.scalar(select(Team.id).where(Team.name_key == team_key)):
                raise APIError("Já existe um time com esse nome.", 409)
            team = Team(
                name=team_name,
                name_key=team_key,
                invite_pin_hash=await run_in_threadpool(hash_password, pin),
                logo_data=logo_data,
            )
            db.add(team)
            db.flush()
            coach = User(
                name=name,
                email=email,
                password_hash=password_hash,
                role="coach",
                team_id=team.id,
            )
            db.add(coach)
            db.flush()
            response = JSONResponse({"user": _account_payload(db, coach)}, status_code=201)
            _new_session(db, coach, response)
    except IntegrityError as error:
        raise APIError("E-mail ou nome do time já cadastrado.", 409) from error
    return response


async def register_player(request: Request) -> Response:
    _check_same_origin(request)
    payload = await _payload(request)
    name = _required_text(payload, "name", "o nome do jogador", 100)
    email = _required_text(payload, "email", "um e-mail", 255).lower()
    password = payload.get("password")
    pin = payload.get("pin")
    if not valid_email_address(email):
        raise APIError("Informe um e-mail válido.", 422)
    if not isinstance(password, str) or len(password) < 8 or len(password) > 128:
        raise APIError("A senha deve conter entre 8 e 128 caracteres.", 422)
    if not isinstance(pin, str) or not is_valid_invite_pin(pin):
        raise APIError("O PIN deve conter de 6 a 12 dígitos numéricos.", 422)
    raw_height = payload.get("height_cm")
    raw_weight = payload.get("weight_kg")
    if (
        isinstance(raw_height, bool)
        or isinstance(raw_weight, bool)
        or not isinstance(raw_height, (int, float, str))
        or not isinstance(raw_weight, (int, float, str))
    ):
        raise APIError("Informe altura e peso válidos.", 422)
    try:
        height = int(raw_height)
        weight = float(raw_weight)
    except (TypeError, ValueError) as error:
        raise APIError("Informe altura e peso válidos.", 422) from error
    position = payload.get("position")
    secondary = payload.get("secondary_position") or None
    preferred_foot = payload.get("preferred_foot") or "Direito"
    team_id = payload.get("team_id")
    if not 100 <= height <= 230 or not 30 <= weight <= 200:
        raise APIError("Altura ou peso fora do intervalo permitido.", 422)
    if not isinstance(position, str) or position not in POSITION_OPTIONS:
        raise APIError("Escolha posições válidas para o jogador.", 422)
    if secondary is not None and (not isinstance(secondary, str) or secondary not in POSITION_OPTIONS):
        raise APIError("Escolha posições válidas para o jogador.", 422)
    if not isinstance(preferred_foot, str) or preferred_foot not in {"Direito", "Esquerdo", "Ambidestro"}:
        raise APIError("Escolha um pé preferido válido.", 422)
    if not isinstance(team_id, int) or isinstance(team_id, bool) or team_id <= 0:
        raise APIError("Selecione um time cadastrado.", 422)
    if not math.isfinite(weight):
        raise APIError("Informe um peso válido.", 422)

    password_hash = await run_in_threadpool(hash_password, password)
    response = JSONResponse({})
    try:
        with SessionLocal.begin() as db:
            if db.scalar(select(User.id).where(User.email == email)):
                raise APIError("Este e-mail já está cadastrado.", 409)
            team = db.get(Team, team_id)
            if not team or not await run_in_threadpool(verify_password, pin, team.invite_pin_hash):
                raise APIError("Time ou PIN inválido. Confirme o convite com o treinador.", 403)
            player = User(
                name=name,
                email=email,
                password_hash=password_hash,
                role="player",
                team_id=team.id,
                height_cm=height,
                weight_kg=weight,
                preferred_foot=preferred_foot,
                primary_position=position,
                secondary_position=secondary,
            )
            db.add(player)
            db.flush()
            response = JSONResponse({"user": _account_payload(db, player)}, status_code=201)
            _new_session(db, player, response)
    except IntegrityError as error:
        raise APIError("Este e-mail já está cadastrado.", 409) from error
    return response


async def login(request: Request) -> Response:
    _check_same_origin(request)
    payload = await _payload(request)
    email = _required_text(payload, "email", "um e-mail", 255).lower()
    password = payload.get("password")
    if not isinstance(password, str) or not password:
        raise APIError("Informe sua senha.", 422)
    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.email == email, User.active.is_(True)))
        if not user or not await run_in_threadpool(verify_password, password, user.password_hash):
            raise APIError("E-mail ou senha inválidos.", 401)
        response = JSONResponse({"user": _account_payload(db, user)})
        _new_session(db, user, response)
        return response


async def logout(request: Request) -> Response:
    _check_same_origin(request)
    response = JSONResponse({"ok": True})
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with SessionLocal.begin() as db:
            db.execute(delete(WebSession).where(WebSession.token_hash == token_hash))
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")
    return response


async def me(request: Request) -> Response:
    with SessionLocal() as db:
        user = _current_user(request, db)
        matches = _team_matches(db, user.team_id)
        players = list(db.scalars(
            select(User).where(
                User.team_id == user.team_id,
                User.role == "player",
                User.active.is_(True),
            ).order_by(User.name)
        ))
        upcoming = next((match for match in reversed(matches) if match.status == "scheduled"), None)
        return JSONResponse({
            "authenticated": True,
            "user": _account_payload(db, user),
            "players": [
                _player_payload(
                    db,
                    player,
                    include_details=user.role == "coach",
                    include_profile=user.role == "coach",
                )
                for player in players
            ],
            "matches": [_match_payload(db, match) for match in matches],
            "upcoming_match_id": upcoming.id if upcoming else None,
        })


async def auth_session(request: Request) -> Response:
    try:
        return await me(request)
    except APIError as error:
        if error.status_code == 401:
            return JSONResponse({"authenticated": False})
        raise


async def list_matches(request: Request) -> Response:
    with SessionLocal() as db:
        user = _current_user(request, db)
        return JSONResponse([_match_payload(db, match) for match in _team_matches(db, user.team_id)])


def _save_roster(db, match: Match, normalized: list[dict]) -> None:
    match.roster.clear()
    db.flush()
    starter_slot = 0
    reserve_slot = len(normalized)
    for item in normalized:
        is_starter = item["is_starter"]
        slot = starter_slot if is_starter else reserve_slot
        if is_starter:
            starter_slot += 1
        else:
            reserve_slot += 1
        match.roster.append(MatchRoster(
            player_id=item["player_id"],
            position=item["position"],
            slot=slot,
            is_starter=is_starter,
            field_x=item["field_x"],
            field_y=item["field_y"],
        ))


def _match_schedule(payload: dict) -> tuple[str, date, time, str | None]:
    opponent = _required_text(payload, "opponent", "o adversário", 100)
    venue = payload.get("venue", "")
    if not isinstance(venue, str) or len(venue.strip()) > 150:
        raise APIError("O local deve ter até 150 caracteres.", 422)
    try:
        played_on = date.fromisoformat(payload.get("played_on", ""))
    except (TypeError, ValueError) as error:
        raise APIError("Informe uma data válida para a partida.", 422) from error
    raw_kickoff_time = payload.get("kickoff_time")
    if not isinstance(raw_kickoff_time, str):
        raise APIError("Informe um horário válido para a partida.", 422)
    try:
        kickoff_time = time.fromisoformat(raw_kickoff_time)
    except ValueError as error:
        raise APIError("Informe um horário válido para a partida.", 422) from error
    if kickoff_time.second or kickoff_time.microsecond:
        raise APIError("Informe o horário no formato HH:MM.", 422)
    return opponent, played_on, kickoff_time, venue.strip() or None


def _result_integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 99:
        raise APIError(f"Informe {label} como um número inteiro entre 0 e 99.", 422)
    return value


def _validate_match_result(payload: dict, roster_ids: set[int]) -> tuple[int, int, list[dict]]:
    home_score = _result_integer(payload.get("home_score"), "os gols do time")
    away_score = _result_integer(payload.get("away_score"), "os gols do adversário")
    entries = payload.get("stats")
    if not isinstance(entries, list) or len(entries) != len(roster_ids):
        raise APIError("Informe as estatísticas de todos os atletas convocados.", 422)
    normalized = []
    seen_ids: set[int] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise APIError("Há uma estatística inválida no resultado.", 422)
        player_id = entry.get("player_id")
        if not isinstance(player_id, int) or isinstance(player_id, bool) or player_id not in roster_ids or player_id in seen_ids:
            raise APIError("O resultado contém atleta fora da convocação ou duplicado.", 422)
        seen_ids.add(player_id)
        normalized.append({
            "player_id": player_id,
            "goals": _result_integer(entry.get("goals"), "os gols do atleta"),
            "assists": _result_integer(entry.get("assists"), "as assistências do atleta"),
            "yellow_cards": _result_integer(entry.get("yellow_cards"), "os cartões amarelos"),
            "red_cards": _result_integer(entry.get("red_cards"), "os cartões vermelhos"),
        })
    if seen_ids != roster_ids:
        raise APIError("Informe as estatísticas de todos os atletas convocados.", 422)
    if sum(item["goals"] for item in normalized) != home_score:
        raise APIError("A soma dos gols dos atletas deve ser igual ao placar do time.", 422)
    if sum(item["assists"] for item in normalized) > home_score:
        raise APIError("O total de assistências não pode superar os gols do time.", 422)
    return home_score, away_score, normalized


async def create_match(request: Request) -> Response:
    _check_same_origin(request)
    payload = await _payload(request)
    opponent, played_on, kickoff_time, venue = _match_schedule(payload)

    with SessionLocal.begin() as db:
        user = _current_user(request, db)
        _coach(user)
        normalized = _validate_roster(db, user.team_id, payload)
        match = Match(
            team_id=user.team_id,
            opponent=opponent,
            played_on=played_on,
            kickoff_time=kickoff_time,
            venue=venue,
            formation=payload.get("formation", "Livre"),
            status="scheduled",
        )
        db.add(match)
        db.flush()
        _save_roster(db, match, normalized)
        db.flush()
        return JSONResponse({"match": _match_payload(db, match)}, status_code=201)


async def update_lineup(request: Request) -> Response:
    _check_same_origin(request)
    payload = await _payload(request)
    try:
        match_id = int(request.path_params["match_id"])
    except (TypeError, ValueError) as error:
        raise APIError("Partida inválida.", 404) from error
    opponent, played_on, kickoff_time, venue = _match_schedule(payload)

    with SessionLocal.begin() as db:
        user = _current_user(request, db)
        _coach(user)
        match = db.scalar(select(Match).where(
            Match.id == match_id,
            Match.team_id == user.team_id,
        ))
        if not match:
            raise APIError("Partida não encontrada neste time.", 404)
        if match.status == "played":
            raise APIError("A escalação de uma partida concluída não pode ser alterada.", 409)
        normalized = _validate_roster(db, user.team_id, payload)
        match.opponent = opponent
        match.played_on = played_on
        match.kickoff_time = kickoff_time
        match.venue = venue
        match.formation = payload.get("formation", "Livre")
        _save_roster(db, match, normalized)
        db.flush()
        return JSONResponse({"match": _match_payload(db, match)})


async def record_match_result(request: Request) -> Response:
    _check_same_origin(request)
    payload = await _payload(request)
    try:
        match_id = int(request.path_params["match_id"])
    except (TypeError, ValueError) as error:
        raise APIError("Partida inválida.", 404) from error

    with SessionLocal.begin() as db:
        user = _current_user(request, db)
        _coach(user)
        match = db.scalar(select(Match).where(
            Match.id == match_id,
            Match.team_id == user.team_id,
        ))
        if not match:
            raise APIError("Partida não encontrada neste time.", 404)
        roster_ids = set(db.scalars(
            select(MatchRoster.player_id).where(MatchRoster.match_id == match.id)
        ))
        if not roster_ids:
            raise APIError("Cadastre a escalação antes de registrar o resultado.", 422)
        home_score, away_score, stats = _validate_match_result(payload, roster_ids)
        current_stats = {
            row.player_id: row
            for row in db.scalars(select(PlayerStats).where(
                PlayerStats.match_id == match.id,
                PlayerStats.player_id.in_(roster_ids),
            ))
        }
        for item in stats:
            player_stats = current_stats.get(item["player_id"])
            if player_stats is None:
                player_stats = PlayerStats(match_id=match.id, player_id=item["player_id"])
                db.add(player_stats)
            player_stats.goals = item["goals"]
            player_stats.assists = item["assists"]
            player_stats.yellow_cards = item["yellow_cards"]
            player_stats.red_cards = item["red_cards"]
        match.home_score = home_score
        match.away_score = away_score
        match.status = "played"
        db.flush()
        return JSONResponse({"match": _match_payload(db, match)})


@asynccontextmanager
async def lifespan(_app: Starlette):
    del _app
    init_db()
    yield


def handle_api_error(_request: Request, error: Exception) -> Response:
    del _request
    if not isinstance(error, APIError):
        raise error
    return _json_error(error)


frontend_path = Path(__file__).resolve().parent / "frontend"
routes = [
    Route("/api/teams", list_teams, methods=["GET"]),
    Route("/api/auth/register/coach", register_coach, methods=["POST"]),
    Route("/api/auth/register/player", register_player, methods=["POST"]),
    Route("/api/auth/login", login, methods=["POST"]),
    Route("/api/auth/logout", logout, methods=["POST"]),
    Route("/api/auth/session", auth_session, methods=["GET"]),
    Route("/api/me", me, methods=["GET"]),
    Route("/api/matches", list_matches, methods=["GET"]),
    Route("/api/matches", create_match, methods=["POST"]),
    Route("/api/matches/{match_id:int}/lineup", update_lineup, methods=["PUT"]),
    Route("/api/matches/{match_id:int}/result", record_match_result, methods=["PUT"]),
    Mount("/", app=StaticFiles(directory=frontend_path, html=True), name="frontend"),
]
app = Starlette(routes=routes, lifespan=lifespan, exception_handlers={APIError: handle_api_error})
