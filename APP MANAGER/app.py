from __future__ import annotations

from datetime import date
from html import escape
from time import time

import pandas as pd
import streamlit as st
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from fut7.database import SessionLocal, init_db
from fut7.logic import calculate_attributes, calculate_final_rating, overall_from_attributes
from fut7.models import Goal, Match, MatchRoster, PlayerStats, Rating, Team, User
from fut7.registration import logo_bytes_from_data, logo_data_from_upload, valid_email_address
from fut7.security import hash_password, is_valid_invite_pin, normalize_team_name, verify_password
from fut7.ui import inject_styles, render_player_card, render_radar

POSITIONS = ["GOL", "ZAG", "ALA", "MEI", "ATA"]
PLAYER_REGISTRATION_KEY = "pending_player_registration"
PLAYER_REGISTRATION_TTL_SECONDS = 30 * 60


@st.cache_resource
def _initialize_database() -> bool:
    init_db()
    return True


_initialize_database()
inject_styles()


def signed_in_user() -> User | None:
    user_id = st.session_state.get("user_id")
    if not user_id:
        return None
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user and user.active and user.team_id:
            return user
    st.session_state.pop("user_id", None)
    return None


def get_players(db, team_id: int) -> list[User]:
    return list(db.scalars(
        select(User).where(User.role == "player", User.team_id == team_id, User.active.is_(True)).order_by(User.name)
    ))


def get_matches(db, team_id: int, status: str | None = None) -> list[Match]:
    query = select(Match).where(Match.team_id == team_id).order_by(Match.played_on.desc(), Match.id.desc())
    if status:
        query = query.where(Match.status == status)
    return list(db.scalars(query))


def attributes_for(db, player: User) -> dict[str, float]:
    stats = list(db.scalars(select(PlayerStats).where(PlayerStats.player_id == player.id)))
    ratings = list(db.scalars(select(Rating).where(Rating.rated_player_id == player.id)))
    return calculate_attributes(player, stats, ratings)


def show_public_teams() -> None:
    st.subheader("Times cadastrados")
    with SessionLocal() as db:
        teams = list(db.scalars(select(Team).order_by(Team.name)))
        team_logos = [(team.name, logo_bytes_from_data(team.logo_data)) for team in teams]
    if not team_logos:
        st.caption("Nenhum time cadastrado ainda.")
        return
    columns = st.columns(3)
    for index, (team_name, logo) in enumerate(team_logos):
        with columns[index % len(columns)]:
            if logo:
                st.image(logo, width=76)
            else:
                st.markdown("⚽")
            st.caption(team_name)


def _return_to_login() -> None:
    st.session_state["auth_view"] = "Entrar"


def show_player_registration() -> None:
    pending = st.session_state.get(PLAYER_REGISTRATION_KEY)
    if pending and time() - pending["created_at"] >= PLAYER_REGISTRATION_TTL_SECONDS:
        st.session_state.pop(PLAYER_REGISTRATION_KEY, None)
        pending = None
        st.warning("Seu cadastro expirou após 30 minutos. Comece novamente.")

    if pending is None or pending["stage"] == "account":
        st.caption("Etapa 1 de 3 — crie seu acesso com nome, e-mail e senha.")
        with st.form("player_registration_account"):
            name = st.text_input("Nome completo", key="player_register_name")
            email = st.text_input("E-mail", key="player_register_email").strip().lower()
            password = st.text_input("Crie uma senha (mínimo 8 caracteres)", type="password",
                                     key="player_register_password")
            confirm = st.text_input("Confirme a senha", type="password", key="player_register_confirm")
            submitted = st.form_submit_button("CONTINUAR PARA O PERFIL", type="primary", use_container_width=True)
        if submitted:
            if not name.strip() or not valid_email_address(email) or len(password) < 8:
                st.error("Informe nome, e-mail válido e uma senha com pelo menos 8 caracteres.")
            elif password != confirm:
                st.error("As senhas não conferem.")
            else:
                with SessionLocal() as db:
                    if db.scalar(select(User.id).where(User.email == email)):
                        st.error("Este e-mail já está cadastrado.")
                    else:
                        st.session_state[PLAYER_REGISTRATION_KEY] = {
                            "stage": "profile",
                            "name": name.strip(),
                            "email": email,
                            "password_hash": hash_password(password),
                            "created_at": time(),
                        }
                        st.rerun()
        return

    if pending["stage"] == "profile":
        st.caption("Etapa 2 de 3 — informe seus dados físicos e posições.")
        with st.form("player_registration_profile"):
            col1, col2 = st.columns(2)
            height = col1.number_input("Altura (cm)", 100, 230, 170)
            weight = col2.number_input("Peso (kg)", 30.0, 200.0, 70.0, step=0.5)
            foot = col1.selectbox("Pé preferido", ["Direito", "Esquerdo", "Ambidestro"])
            position = col2.selectbox("Posição principal", POSITIONS)
            secondary_options = ["Sem segunda posição"] + [item for item in POSITIONS if item != position]
            secondary_position = st.selectbox("Segunda posição", secondary_options)
            photo_url = st.text_input("URL da foto (opcional)")
            submitted = st.form_submit_button("CONTINUAR PARA O TIME", type="primary", use_container_width=True)
        if submitted:
            pending.update({
                "stage": "team",
                "height_cm": int(height),
                "weight_kg": float(weight),
                "preferred_foot": foot,
                "primary_position": position,
                "secondary_position": None if secondary_position == "Sem segunda posição" else secondary_position,
                "photo_url": photo_url.strip() or None,
            })
            st.session_state[PLAYER_REGISTRATION_KEY] = pending
            st.rerun()
        return

    st.caption("Etapa 3 de 3 — escolha o time e informe o PIN recebido do treinador.")
    with SessionLocal() as db:
        teams = list(db.scalars(select(Team).order_by(Team.name)))
        team_names = {team.id: team.name for team in teams}
        if teams:
            with st.form("player_registration_team"):
                team_id = st.selectbox("Time", list(team_names), format_func=team_names.__getitem__)
                invite_pin = st.text_input("PIN do treinador", type="password", max_chars=12)
                submitted = st.form_submit_button("VALIDAR PIN E CONCLUIR", type="primary", use_container_width=True)
            if submitted:
                team = db.get(Team, team_id)
                if not is_valid_invite_pin(invite_pin):
                    st.error("O PIN deve conter de 6 a 12 dígitos numéricos.")
                elif team is None or not verify_password(invite_pin, team.invite_pin_hash):
                    st.error("PIN inválido. Confira o código com o treinador.")
                elif db.scalar(select(User.id).where(User.email == pending["email"])):
                    st.error("Este e-mail já está cadastrado. Faça login ou use outro e-mail.")
                else:
                    player = User(
                        name=pending["name"], email=pending["email"], password_hash=pending["password_hash"],
                        role="player", team_id=team.id, height_cm=pending["height_cm"],
                        weight_kg=pending["weight_kg"], preferred_foot=pending["preferred_foot"],
                        primary_position=pending["primary_position"],
                        secondary_position=pending["secondary_position"], photo_url=pending["photo_url"],
                    )
                    db.add(player)
                    try:
                        db.commit()
                        st.session_state.user_id = player.id
                        st.session_state["auth_success_message"] = f"Cadastro concluído e vinculado a {team.name}."
                        st.session_state.pop(PLAYER_REGISTRATION_KEY, None)
                        st.rerun()
                    except IntegrityError:
                        db.rollback()
                        st.error("Não foi possível concluir o cadastro. Confira se o e-mail já está em uso.")
        else:
            st.info("Ainda não há times cadastrados. Volte à tela de entrada para consultar os times disponíveis.")

    st.button("NÃO TENHO TIME", key="player_registration_no_team", use_container_width=True,
              on_click=_return_to_login)


def show_coach_registration() -> None:
    st.caption("Crie sua conta de treinador, cadastre o time e defina o PIN que será compartilhado com os atletas.")
    with st.form("coach_register"):
        team_name = st.text_input("Nome do time", key="new_team_name")
        logo_file = st.file_uploader("Escudo do time (PNG, JPEG ou WebP; até 2 MB)", type=["png", "jpg", "jpeg", "webp"])
        name = st.text_input("Nome do treinador", key="new_coach_name")
        email = st.text_input("E-mail do treinador", key="new_coach_email").strip().lower()
        password = st.text_input("Crie uma senha (mínimo 8 caracteres)", type="password", key="new_coach_password")
        confirm = st.text_input("Confirme a senha", type="password", key="new_coach_confirm")
        invite_pin = st.text_input("Defina o PIN de convite (6 a 12 dígitos)", type="password",
                                   max_chars=12, key="new_team_pin")
        confirm_pin = st.text_input("Confirme o PIN", type="password", max_chars=12, key="new_team_pin_confirm")
        st.caption("Guarde o PIN: ele não poderá ser consultado depois. Você será responsável por compartilhá-lo.")
        submitted = st.form_submit_button("CRIAR TIME E CONTA DO TREINADOR", type="primary", use_container_width=True)
    if not submitted:
        return
    if not team_name.strip() or not name.strip() or not valid_email_address(email) or len(password) < 8:
        st.error("Informe nome do time, nome do treinador, e-mail válido e senha com pelo menos 8 caracteres.")
    elif password != confirm:
        st.error("As senhas não conferem.")
    elif not is_valid_invite_pin(invite_pin) or invite_pin != confirm_pin:
        st.error("Confirme um PIN numérico de 6 a 12 dígitos.")
    else:
        try:
            logo_data = logo_data_from_upload(logo_file)
        except ValueError as error:
            st.error(str(error))
            return
        team_key = normalize_team_name(team_name)
        with SessionLocal() as db:
            if db.scalar(select(Team.id).where(Team.name_key == team_key)):
                st.error("Já existe um time com esse nome.")
            elif db.scalar(select(User.id).where(User.email == email)):
                st.error("Este e-mail já está cadastrado.")
            else:
                team = Team(
                    name=team_name.strip(), name_key=team_key, invite_pin_hash=hash_password(invite_pin),
                    logo_data=logo_data,
                )
                db.add(team)
                db.flush()
                coach = User(
                    name=name.strip(), email=email, password_hash=hash_password(password),
                    role="coach", team_id=team.id,
                )
                db.add(coach)
                try:
                    db.commit()
                    st.session_state.user_id = coach.id
                    st.session_state["auth_success_message"] = (
                        f"Time {team.name} criado. Compartilhe o PIN definido com seus atletas."
                    )
                    st.rerun()
                except IntegrityError:
                    db.rollback()
                    st.error("Este e-mail já está cadastrado ou o time já existe.")


def show_login() -> None:
    st.markdown('<div class="section-kicker">CLUBE · FUT7 MANAGER</div>', unsafe_allow_html=True)
    st.title("Entre em campo.")
    st.caption("Gestão de elenco, desempenho e evolução — em um só lugar.")
    auth_view = st.radio("Acesso", ["Entrar", "Cadastrar"], horizontal=True, key="auth_view")

    if auth_view == "Entrar":
        with st.form("login_form"):
            email = st.text_input("E-mail").strip().lower()
            password = st.text_input("Senha", type="password")
            submitted = st.form_submit_button("ENTRAR", type="primary", use_container_width=True)
        if submitted:
            with SessionLocal() as db:
                user = db.scalar(select(User).where(
                    User.email == email, User.active.is_(True), User.team_id.is_not(None)
                ))
                if user and verify_password(password, user.password_hash):
                    st.session_state.user_id = user.id
                    st.rerun()
                st.error("E-mail ou senha inválidos.")
        show_public_teams()
        return

    registration_role = st.radio(
        "Quero me cadastrar como",
        ["Sou jogador de um time", "Sou treinador de um time"],
        horizontal=True,
        key="registration_role",
    )
    if registration_role == "Sou jogador de um time":
        show_player_registration()
    else:
        show_coach_registration()


def page_team_invite(user: User) -> None:
    st.markdown('<div class="section-kicker">TIME · ACESSO DE ATLETAS</div>', unsafe_allow_html=True)
    st.title("Time & convite")
    if user.role != "coach":
        st.info("As informações de convite ficam disponíveis para o treinador.")
        return
    with SessionLocal() as db:
        team = db.get(Team, user.team_id)
        if team is None:
            st.error("Não foi possível localizar o time deste treinador.")
            return
        st.metric("TIME", team.name)
        logo = logo_bytes_from_data(team.logo_data)
        if logo is not None:
            st.image(logo, width=120)
        st.info("Compartilhe o PIN com os atletas. Deixe o campo de PIN vazio para manter o código atual; o código salvo não pode ser consultado.")
        with st.form("team_invite_settings"):
            team_name = st.text_input("Nome do time", value=team.name, max_chars=100)
            logo_file = st.file_uploader(
                "Atualizar escudo (PNG, JPEG ou WebP; até 2 MB)",
                type=["png", "jpg", "jpeg", "webp"],
                key="team_logo_update",
            )
            remove_logo = st.checkbox("Remover escudo atual")
            invite_pin = st.text_input("Novo PIN (opcional; 6 a 12 dígitos)", type="password", max_chars=12)
            submitted = st.form_submit_button("SALVAR DADOS DO TIME", type="primary")
        if submitted:
            team_key = normalize_team_name(team_name)
            if not team_name.strip():
                st.error("Informe o nome do time.")
            elif invite_pin and not is_valid_invite_pin(invite_pin):
                st.error("O PIN deve conter de 6 a 12 dígitos numéricos.")
            elif remove_logo and logo_file is not None:
                st.error("Escolha entre remover o escudo atual ou enviar um novo.")
            elif db.scalar(select(Team.id).where(Team.name_key == team_key, Team.id != team.id)):
                st.error("Já existe outro time com esse nome.")
            else:
                try:
                    logo_data = logo_data_from_upload(logo_file)
                except ValueError as error:
                    st.error(str(error))
                else:
                    team.name = team_name.strip()
                    team.name_key = team_key
                    if remove_logo:
                        team.logo_data = None
                    elif logo_data is not None:
                        team.logo_data = logo_data
                    if invite_pin:
                        team.invite_pin_hash = hash_password(invite_pin)
                    db.commit()
                    st.success("Dados do time atualizados.")
                    st.rerun()


def page_dashboard(user: User) -> None:
    st.markdown('<div class="section-kicker">PAINEL DO CLUBE</div>', unsafe_allow_html=True)
    st.title(f"Olá, {user.name.split()[0]}.")
    with SessionLocal() as db:
        players = get_players(db, user.team_id)
        matches = get_matches(db, user.team_id)
        upcoming = [match for match in matches if match.status == "scheduled"]
        played = [match for match in matches if match.status == "played"]
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("ATLETAS", len(players))
        col2.metric("JOGOS REALIZADOS", len(played))
        col3.metric("PRÓXIMO JOGO", upcoming[0].opponent if upcoming else "—")
        col4.metric(
            "META ATIVA",
            db.scalar(
                select(func.count(Goal.id))
                .join(User, Goal.player_id == User.id)
                .where(User.team_id == user.team_id, Goal.completed.is_(False))
            ) or 0,
        )
        st.subheader("Agenda")
        if matches:
            st.dataframe(pd.DataFrame([{
                "Data": match.played_on.strftime("%d/%m/%Y"),
                "Confronto": f"FUT7 × {match.opponent}",
                "Local": match.venue or "—",
                "Status": "Agendada" if match.status == "scheduled" else "Finalizada",
                "Formação": match.formation,
            } for match in matches[:8]]), hide_index=True, use_container_width=True)
        else:
            st.info("Nenhum jogo cadastrado. Crie uma partida para começar a escalar o time.")


def page_roster(user: User) -> None:
    st.markdown('<div class="section-kicker">GESTÃO DO ELENCO</div>', unsafe_allow_html=True)
    st.title("Atletas")
    if user.role == "coach":
        st.caption("Atletas concluem o vínculo ao escolher o time e validar o PIN recebido no cadastro.")
    with SessionLocal() as db:
        players = get_players(db, user.team_id)
        if user.role == "player":
            players = [player for player in players if player.id == user.id]
        if not players:
            st.info("Nenhum atleta aceitou o convite do time ainda.")
            return
        player_map = {player.name: player for player in players}
        selected_name = st.selectbox("Perfil do atleta", list(player_map), index=0)
        selected = player_map[selected_name]
        col_card, col_radar = st.columns([0.85, 1.15], gap="large")
        attributes = attributes_for(db, selected)
        with col_card:
            render_player_card(selected, attributes)
        with col_radar:
            st.subheader("Radar de atributos")
            render_radar(attributes)
        if user.role == "coach" or selected.id == user.id:
            st.divider()
            with st.expander("Editar dados do atleta" if selected.id == user.id else "Editar dados ou desativar atleta"):
                with st.form(f"edit_player_{selected.id}"):
                    new_name = st.text_input("Nome", value=selected.name)
                    col1, col2 = st.columns(2)
                    new_height = col1.number_input("Altura (cm)", 100, 230, selected.height_cm or 170)
                    new_weight = col2.number_input("Peso (kg)", 30.0, 200.0, float(selected.weight_kg or 70))
                    new_foot = col1.selectbox("Pé preferido", ["Direito", "Esquerdo", "Ambidestro"],
                                             index=["Direito", "Esquerdo", "Ambidestro"].index(selected.preferred_foot or "Direito"))
                    new_position = col2.selectbox("Posição", POSITIONS,
                                                 index=POSITIONS.index(selected.primary_position) if selected.primary_position in POSITIONS else 0)
                    secondary_options = ["Sem segunda posição"] + [item for item in POSITIONS if item != new_position]
                    secondary_label = selected.secondary_position or "Sem segunda posição"
                    new_secondary_position = st.selectbox(
                        "Segunda posição", secondary_options,
                        index=secondary_options.index(secondary_label) if secondary_label in secondary_options else 0,
                    )
                    new_photo_url = st.text_input("URL da foto (opcional)", value=selected.photo_url or "")
                    save = st.form_submit_button("SALVAR ALTERAÇÕES", type="primary")
                if save:
                    selected.name = new_name.strip()
                    selected.height_cm = int(new_height)
                    selected.weight_kg = float(new_weight)
                    selected.preferred_foot = new_foot
                    selected.primary_position = new_position
                    selected.secondary_position = (
                        None if new_secondary_position == "Sem segunda posição" else new_secondary_position
                    )
                    selected.photo_url = new_photo_url.strip() or None
                    db.commit()
                    st.success("Perfil atualizado.")
                    st.rerun()
                if user.role == "coach" and selected.id != user.id:
                    if st.button("Desativar atleta", key=f"deactivate_{selected.id}"):
                        selected.active = False
                        db.commit()
                        st.success("Atleta desativado; os dados históricos foram preservados.")
                        st.rerun()


def page_matches(user: User) -> None:
    st.markdown('<div class="section-kicker">CENTRO TÁTICO</div>', unsafe_allow_html=True)
    st.title("Partidas & escalação")
    with SessionLocal() as db:
        players = get_players(db, user.team_id)
        if user.role == "coach":
            with st.expander("＋ Criar partida"):
                with st.form("create_match"):
                    opponent = st.text_input("Adversário")
                    col1, col2 = st.columns(2)
                    played_on = col1.date_input("Data", value=date.today())
                    venue = col2.text_input("Local")
                    formation = st.selectbox("Formação", ["2-3-1", "3-2-1", "2-2-2", "1-3-2"])
                    selected_names = st.multiselect("Convocados", [p.name for p in players])
                    submitted = st.form_submit_button("CRIAR PARTIDA", type="primary")
                if submitted:
                    if not opponent.strip():
                        st.error("Informe o nome do adversário.")
                    else:
                        match = Match(team_id=user.team_id, opponent=opponent.strip(), played_on=played_on, venue=venue.strip() or None,
                                      formation=formation, status="scheduled")
                        db.add(match)
                        db.flush()
                        selected_players = [p for p in players if p.name in selected_names]
                        positions = ["GOL", "ZAG", "ZAG", "ALA", "MEI", "MEI", "ATA"]
                        for index, player in enumerate(selected_players):
                            db.add(MatchRoster(match_id=match.id, player_id=player.id,
                                               position=player.primary_position or positions[min(index, 6)], slot=index))
                        db.commit()
                        st.success("Partida criada e atletas convocados.")
                        st.rerun()

        matches = get_matches(db, user.team_id)
        if not matches:
            st.info("Cadastre a primeira partida para montar a escalação.")
            return
        selected_match = st.selectbox("Partida", matches, format_func=lambda m: f"{m.played_on:%d/%m/%Y} · FUT7 × {m.opponent}")
        roster = list(db.scalars(select(MatchRoster).where(MatchRoster.match_id == selected_match.id).order_by(MatchRoster.slot)))
        st.caption(f"{selected_match.venue or 'Local a definir'} · Formação {selected_match.formation} · {len(roster)} convocados")
        if roster:
            lines = [
                [item for item in roster if item.position == "ATA"],
                [item for item in roster if item.position in {"ALA", "MEI"} or not item.position],
                [item for item in roster if item.position == "ZAG"],
                [item for item in roster if item.position == "GOL"],
            ]
            pitch_rows = []
            for line in lines:
                if line:
                    badges = "".join(
                        f'<div style="min-width:76px;padding:7px 10px;border-radius:12px;background:#0f172add;'
                        f'border:1px solid #4ade80;color:#fff;font-size:12px"><b>{escape(item.position or "LIVRE")}</b><br>'
                        f'{escape(item.player.name)}</div>'
                        for item in line
                    )
                    pitch_rows.append(f'<div style="display:flex;justify-content:center;gap:14px;margin:20px 0">{badges}</div>')
            players_markup = "".join(pitch_rows)
        else:
            players_markup = '<div style="padding:80px 0;color:#d1fae5">Nenhum atleta convocado</div>'
        st.markdown(
            f"""<div style="border:1px solid #1e6b45;border-radius:20px;padding:18px;
            background:repeating-linear-gradient(0deg,#123b2d,#123b2d 62px,#174532 63px,#174532 124px);
            box-shadow:inset 0 0 0 2px #ffffff12;min-height:320px;text-align:center;color:#d1fae5">
            <div style="font-size:11px;letter-spacing:.2em;color:#86efac">CAMPO TÁTICO · {selected_match.formation}</div>
            <div style="height:16px"></div>{players_markup}<div style="border-top:1px solid #86efac66;width:76%;margin:16px auto 0"></div>
            </div>""",
            unsafe_allow_html=True,
        )

        if user.role == "coach" and players:
            with st.expander("Editar convocados e posições"):
                current_ids = {row.player_id for row in roster}
                selected_ids = st.multiselect("Atletas convocados", players, default=[p for p in players if p.id in current_ids],
                                              format_func=lambda p: p.name, key=f"roster_{selected_match.id}")
                if st.button("SALVAR ESCALAÇÃO", type="primary", key=f"save_roster_{selected_match.id}"):
                    for row in list(roster):
                        db.delete(row)
                    for index, player in enumerate(selected_ids):
                        db.add(MatchRoster(match_id=selected_match.id, player_id=player.id,
                                           position=player.primary_position or POSITIONS[min(index, 4)], slot=index))
                    db.commit()
                    st.success("Escalação atualizada.")
                    st.rerun()


def page_goals(user: User) -> None:
    st.markdown('<div class="section-kicker">EVOLUÇÃO CONTÍNUA</div>', unsafe_allow_html=True)
    st.title("Metas individuais")
    with SessionLocal() as db:
        players = get_players(db, user.team_id)
        matches = get_matches(db, user.team_id)
        if user.role == "coach" and players:
            with st.expander("＋ Definir meta"):
                with st.form("new_goal"):
                    player = st.selectbox("Atleta", players, format_func=lambda p: p.name)
                    match = st.selectbox("Partida", [None] + matches,
                                         format_func=lambda m: "Meta geral" if m is None else f"{m.played_on:%d/%m} × {m.opponent}")
                    description = st.text_input("Descrição", placeholder="Ex.: completar 3 desarmes")
                    target = st.number_input("Alvo numérico", min_value=1, max_value=100, value=1)
                    submitted = st.form_submit_button("DEFINIR META", type="primary")
                if submitted:
                    if not description.strip():
                        st.error("Descreva a meta.")
                    else:
                        db.add(Goal(player_id=player.id, match_id=match.id if match else None,
                                    description=description.strip(), target_value=int(target)))
                        db.commit()
                        st.success("Meta cadastrada.")
                        st.rerun()
        query = select(Goal).join(User, Goal.player_id == User.id).where(User.team_id == user.team_id)
        if user.role == "player":
            query = query.where(Goal.player_id == user.id)
        query = query.order_by(Goal.completed, Goal.id.desc())
        goals = list(db.scalars(query))
        if not goals:
            st.info("Nenhuma meta cadastrada.")
        for goal in goals:
            owner = goal.player.name
            match_label = f" · {goal.match.opponent}" if goal.match else ""
            st.markdown(f"**{owner}**{match_label} — {goal.description}  \n`{goal.progress}/{goal.target_value}`")
            if user.role == "player" and goal.player_id == user.id and not goal.completed:
                new_progress = st.slider("Progresso", 0, goal.target_value, min(goal.progress, goal.target_value), key=f"goal_{goal.id}")
                if st.button("ATUALIZAR PROGRESSO", key=f"update_goal_{goal.id}"):
                    goal.progress = new_progress
                    goal.completed = new_progress >= goal.target_value
                    db.commit()
                    st.rerun()
            else:
                st.progress(min(goal.progress / max(goal.target_value, 1), 1.0))


def page_post_match(user: User) -> None:
    st.markdown('<div class="section-kicker">ANÁLISE PÓS-JOGO</div>', unsafe_allow_html=True)
    st.title("Estatísticas & desempenho")
    if user.role != "coach":
        st.info("As estatísticas oficiais são lançadas pelo treinador.")
        return
    with SessionLocal() as db:
        matches = get_matches(db, user.team_id, status="scheduled") + get_matches(db, user.team_id, status="played")
        if not matches:
            st.info("Cadastre uma partida e sua escalação primeiro.")
            return
        match = st.selectbox("Partida", matches, format_func=lambda m: f"{m.played_on:%d/%m/%Y} · FUT7 × {m.opponent}",
                             key="stats_match")
        roster = list(db.scalars(select(MatchRoster).where(MatchRoster.match_id == match.id).order_by(MatchRoster.slot)))
        if not roster:
            st.warning("Essa partida ainda não tem atletas convocados.")
            return
        with st.form(f"stats_form_{match.id}"):
            values = {}
            for item in roster:
                existing = db.scalar(select(PlayerStats).where(PlayerStats.match_id == match.id, PlayerStats.player_id == item.player_id))
                st.markdown(f"**{item.player.name}** · {item.position}")
                cols = st.columns(7)
                defaults = [existing.goals, existing.assists, existing.shots_on_target, existing.tackles,
                            existing.yellow_cards, existing.red_cards, existing.coach_rating if existing.coach_rating is not None else 3.0] if existing else [0, 0, 0, 0, 0, 0, 3.0]
                values[item.player_id] = (
                    cols[0].number_input("Gols", 0, 30, defaults[0], key=f"g_{item.player_id}_{match.id}"),
                    cols[1].number_input("Assist.", 0, 30, defaults[1], key=f"a_{item.player_id}_{match.id}"),
                    cols[2].number_input("Chutes", 0, 40, defaults[2], key=f"s_{item.player_id}_{match.id}"),
                    cols[3].number_input("Desarmes", 0, 40, defaults[3], key=f"t_{item.player_id}_{match.id}"),
                    cols[4].number_input("Amarelos", 0, 2, defaults[4], key=f"y_{item.player_id}_{match.id}"),
                    cols[5].number_input("Vermelhos", 0, 1, defaults[5], key=f"r_{item.player_id}_{match.id}"),
                    cols[6].number_input("Nota técnico", 0.0, 5.0, float(defaults[6]), step=0.5, key=f"c_{item.player_id}_{match.id}"),
                )
            submitted = st.form_submit_button("SALVAR PÓS-JOGO", type="primary", use_container_width=True)
        if submitted:
            for player_id, stat_values in values.items():
                stats = db.scalar(select(PlayerStats).where(PlayerStats.match_id == match.id, PlayerStats.player_id == player_id))
                if stats is None:
                    stats = PlayerStats(match_id=match.id, player_id=player_id)
                    db.add(stats)
                stats.goals, stats.assists, stats.shots_on_target, stats.tackles, stats.yellow_cards, stats.red_cards, stats.coach_rating = stat_values
            match.status = "played"
            db.commit()
            st.success("Estatísticas salvas. Os atletas convocados já podem avaliar os companheiros.")

        st.subheader("Notas finais")
        rows = []
        for item in roster:
            stats = db.scalar(select(PlayerStats).where(PlayerStats.match_id == match.id, PlayerStats.player_id == item.player_id))
            peer_ratings = list(db.scalars(select(Rating).where(Rating.match_id == match.id, Rating.rated_player_id == item.player_id)))
            if stats:
                final_rating = calculate_final_rating(stats.coach_rating, peer_ratings)
                rows.append({"Atleta": item.player.name, "Nota técnico": stats.coach_rating,
                             "Média anônima": round(sum(r.score for r in peer_ratings) / len(peer_ratings), 2) if peer_ratings else "Aguardando",
                             "Nota final": final_rating if final_rating is not None else "Aguardando"})
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.caption("Nota final = (média das avaliações dos companheiros + nota do treinador) ÷ 2. É exibida após ao menos uma avaliação anônima.")


def page_ratings(user: User) -> None:
    st.markdown('<div class="section-kicker">VESTIÁRIO · FEEDBACK</div>', unsafe_allow_html=True)
    st.title("Avaliação dos companheiros")
    if user.role != "player":
        st.info("Este espaço é reservado aos atletas.")
        return
    with SessionLocal() as db:
        matches = list(db.scalars(
            select(Match).join(MatchRoster).where(
                Match.team_id == user.team_id, Match.status == "played", MatchRoster.player_id == user.id
            )
            .order_by(Match.played_on.desc()).distinct()
        ))
        if not matches:
            st.info("As avaliações ficam disponíveis após uma partida em que você foi convocado.")
            return
        match = st.selectbox("Partida avaliada", matches, format_func=lambda m: f"{m.played_on:%d/%m/%Y} · FUT7 × {m.opponent}")
        roster = list(db.scalars(select(MatchRoster).where(MatchRoster.match_id == match.id, MatchRoster.player_id != user.id)))
        if not roster:
            st.info("Não há outros atletas nesta convocação para avaliar.")
            return
        st.caption("As notas são anônimas: o treinador e os atletas não veem quem enviou cada avaliação.")
        with st.form(f"ratings_{match.id}_{user.id}"):
            entries = []
            for item in roster:
                existing = db.scalar(select(Rating).where(Rating.match_id == match.id, Rating.rater_id == user.id,
                                                         Rating.rated_player_id == item.player_id))
                score = st.slider(item.player.name, 0.0, 5.0, existing.score if existing else 3.0, step=0.5,
                                  key=f"rating_{match.id}_{user.id}_{item.player_id}")
                entries.append((item.player_id, score))
            submitted = st.form_submit_button("ENVIAR AVALIAÇÕES", type="primary")
        if submitted:
            for player_id, score in entries:
                rating = db.scalar(select(Rating).where(Rating.match_id == match.id, Rating.rater_id == user.id,
                                                       Rating.rated_player_id == player_id))
                if rating is None:
                    db.add(Rating(match_id=match.id, rater_id=user.id, rated_player_id=player_id, score=score))
                else:
                    rating.score = score
            db.commit()
            st.success("Avaliações registradas. Obrigado pelo feedback!")


def page_reports(user: User) -> None:
    st.markdown('<div class="section-kicker">SCOUTING & DADOS</div>', unsafe_allow_html=True)
    st.title("Relatórios do elenco")
    with SessionLocal() as db:
        players = get_players(db, user.team_id)
        rows = []
        for player in players:
            stats = list(db.scalars(select(PlayerStats).where(PlayerStats.player_id == player.id)))
            total_games = len(stats)
            goals = sum(row.goals for row in stats)
            assists = sum(row.assists for row in stats)
            attributes = calculate_attributes(player, stats, db.scalars(select(Rating).where(Rating.rated_player_id == player.id)))
            rows.append({"Atleta": player.name, "Posição": player.primary_position or "—", "Jogos": total_games,
                         "Gols": goals, "Assistências": assists, "Overall": overall_from_attributes(attributes)})
        if rows:
            frame = pd.DataFrame(rows).sort_values(["Overall", "Atleta"], ascending=[False, True])
            st.dataframe(frame, hide_index=True, use_container_width=True)
            st.bar_chart(frame.set_index("Atleta")[["Gols", "Assistências"]], color=["#22c55e", "#3b82f6"])
        else:
            st.info("Cadastre atletas para começar a gerar relatórios.")


user = signed_in_user()
if user is None:
    show_login()
else:
    success_message = st.session_state.pop("auth_success_message", None)
    if success_message:
        st.success(success_message)
    with st.sidebar:
        st.markdown('<div class="section-kicker">FUT7 MANAGER</div>', unsafe_allow_html=True)
        st.markdown(f"**{user.name}**  \n{'Treinador' if user.role == 'coach' else 'Atleta'}")
        with SessionLocal() as db:
            team = db.get(Team, user.team_id)
            if team:
                st.caption(f"TIME · {team.name}")
        if st.button("Sair", use_container_width=True):
            st.session_state.pop("user_id", None)
            st.session_state["auth_view"] = "Entrar"
            st.rerun()
        options = ["Painel", "Elenco & cards", "Partidas & escalação", "Metas", "Meu desempenho"]
        if user.role == "coach":
            options += ["Pós-jogo", "Relatórios", "Time & convite"]
        else:
            options += ["Avaliar companheiros"]
        page = st.radio("NAVEGAÇÃO", options, label_visibility="collapsed")

    if page == "Painel":
        page_dashboard(user)
    elif page == "Elenco & cards":
        page_roster(user)
    elif page == "Partidas & escalação":
        page_matches(user)
    elif page == "Metas":
        page_goals(user)
    elif page == "Meu desempenho":
        with SessionLocal() as db:
            player = db.get(User, user.id)
            if player is None:
                st.error("Não foi possível carregar o perfil deste atleta.")
                st.stop()
            attributes = attributes_for(db, player)
            col1, col2 = st.columns([0.85, 1.15], gap="large")
            with col1:
                render_player_card(player, attributes)
            with col2:
                st.subheader("Radar de atributos")
                render_radar(attributes)
                st.caption("Atributos estimados a partir dos dados de cadastro, estatísticas e notas. Não representam métricas físicas medidas.")
            st.divider()
            st.subheader("Meu histórico de partidas")
            player_stats = list(db.scalars(
                select(PlayerStats).where(PlayerStats.player_id == player.id).order_by(PlayerStats.match_id.desc())
            ))
            history = []
            for stats in player_stats:
                match = db.get(Match, stats.match_id)
                if match is None:
                    st.error("Não foi possível carregar uma partida do histórico deste atleta.")
                    st.stop()
                peer_ratings = list(db.scalars(select(Rating).where(
                    Rating.match_id == stats.match_id, Rating.rated_player_id == player.id
                )))
                peer_average = round(sum(item.score for item in peer_ratings) / len(peer_ratings), 2) if peer_ratings else None
                final_rating = calculate_final_rating(stats.coach_rating, peer_ratings)
                history.append({
                    "Data": match.played_on.strftime("%d/%m/%Y"),
                    "Adversário": match.opponent,
                    "Gols": stats.goals,
                    "Assistências": stats.assists,
                    "Chutes no alvo": stats.shots_on_target,
                    "Desarmes": stats.tackles,
                    "Amarelos": stats.yellow_cards,
                    "Vermelhos": stats.red_cards,
                    "Nota técnico": stats.coach_rating if stats.coach_rating is not None else "—",
                    "Média anônima": peer_average if peer_average is not None else "Aguardando",
                    "Nota final": final_rating if final_rating is not None else "Aguardando",
                })
            if history:
                st.dataframe(pd.DataFrame(history), hide_index=True, use_container_width=True)
            else:
                st.info("Suas estatísticas aparecerão aqui após o treinador registrar uma partida.")
    elif page == "Pós-jogo":
        page_post_match(user)
    elif page == "Relatórios":
        page_reports(user)
    elif page == "Time & convite":
        page_team_invite(user)
    elif page == "Avaliar companheiros":
        page_ratings(user)
