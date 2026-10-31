from __future__ import annotations

from html import escape
from urllib.parse import urlparse

import plotly.graph_objects as go
import streamlit as st

from fut7.logic import ATTRIBUTE_LABELS, overall_from_attributes
from fut7.models import User


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700;800;900&family=Inter:wght@400;500;600;700&display=swap');
        :root { color-scheme: dark; }
        .stApp { background: radial-gradient(ellipse at 12% 0%, #14253a 0, #0f172a 48%, #080d18 100%); color: #e5e7eb; }
        html, body, [class*="css"] { font-family: Inter, sans-serif; }
        h1, h2, h3, .stat-value, .eyebrow { font-family: 'Barlow Condensed', sans-serif !important; letter-spacing: .04em; }
        .block-container { max-width: 1320px; padding-top: 2rem; }
        [data-testid="stMetric"] { background: #111d30; border: 1px solid #263852; border-radius: 14px; padding: 16px 18px; }
        [data-testid="stMetricLabel"] { color: #91a2ba; }
        [data-testid="stMetricValue"] { color: #f8fafc; font-family: 'Barlow Condensed', sans-serif; }
        .player-card { position: relative; overflow: hidden; min-height: 390px; padding: 24px; border-radius: 22px;
          background: linear-gradient(145deg, #263d38 0%, #17271f 44%, #111827 100%);
          border: 1px solid rgba(245,158,11,.75); box-shadow: 0 0 30px rgba(34,197,94,.12), inset 0 0 36px rgba(245,158,11,.08); }
        .player-card:after { content: ''; position:absolute; width:270px; height:270px; right:-100px; top:-90px;
          border:1px solid rgba(34,197,94,.35); transform:rotate(45deg); box-shadow:0 0 22px rgba(34,197,94,.17); }
        .card-top { display:flex; justify-content:space-between; align-items:flex-start; position:relative; z-index:1; }
        .overall { color:#fbbf24; font:900 58px 'Barlow Condensed',sans-serif; line-height:.9; text-shadow:0 0 18px #f59e0b66; }
        .position { color:#d1fae5; font:700 19px 'Barlow Condensed',sans-serif; letter-spacing:.1em; }
        .avatar { width:128px; height:128px; border-radius:50%; margin:22px auto 15px; display:grid; place-items:center;
          color:#d1fae5; font:800 48px 'Barlow Condensed',sans-serif; background:radial-gradient(circle at 35% 30%,#3b82f6,#143a36 65%,#0b1720);
          border:2px solid #22c55e; box-shadow:0 0 24px #22c55e44; object-fit:cover; }
        .player-name { text-align:center; color:#fff; font:800 27px 'Barlow Condensed',sans-serif; text-transform:uppercase; }
        .card-meta { display:flex; justify-content:center; gap:18px; color:#cbd5e1; font-size:12px; text-transform:uppercase; margin:4px 0 20px; }
        .card-stats { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; text-align:center; border-top:1px solid #ffffff20; padding-top:15px; }
        .card-stats b { display:block; font:800 23px 'Barlow Condensed',sans-serif; color:#86efac; }
        .card-stats span { color:#aab8ca; font:600 10px Inter,sans-serif; letter-spacing:.07em; }
        .section-kicker { color:#22c55e; font:700 12px Inter,sans-serif; letter-spacing:.18em; text-transform:uppercase; }
        div.stButton > button[kind="primary"] { background:linear-gradient(90deg,#16a34a,#22c55e); border:0; color:#07120b; font-weight:800; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_player_card(player: User, attributes: dict[str, float]) -> None:
    overall = overall_from_attributes(attributes)
    initials = escape("".join(part[0] for part in player.name.split()[:2]).upper())
    position = escape(player.primary_position or "ATLETA")
    secondary_position = escape(player.secondary_position or "")
    name = escape(player.name)
    foot = escape(player.preferred_foot or "—")
    secondary_label = f"<span>↗ 2ª {secondary_position}</span>" if secondary_position else ""
    image_url = (player.photo_url or "").strip()
    parsed_url = urlparse(image_url)
    if parsed_url.scheme in {"http", "https"} and parsed_url.netloc:
        portrait = f'<img class="avatar" src="{escape(image_url, quote=True)}" alt="Foto de {name}">'
    else:
        portrait = f'<div class="avatar">{initials}</div>'
    st.markdown(
        f"""
        <div class="player-card">
          <div class="card-top"><div><div class="overall">{overall}</div><div class="position">{position}</div></div>
          <div class="section-kicker">FUT7 · ELITE</div></div>
          {portrait}
          <div class="player-name">{name}</div>
          <div class="card-meta"><span>⚽ FUT 7</span><span>◉ PÉ {foot}</span>{secondary_label}</div>
          <div class="card-stats">
            <div><b>{round(attributes.get("Ataque", 0))}</b><span>ATA</span></div>
            <div><b>{round(attributes.get("Técnica", 0))}</b><span>TEC</span></div>
            <div><b>{round(attributes.get("Velocidade", 0))}</b><span>VEL</span></div>
            <div><b>{round(attributes.get("Defesa", 0))}</b><span>DEF</span></div>
            <div><b>{round(attributes.get("Força", 0))}</b><span>FOR</span></div>
            <div><b>{round(attributes.get("Inteligência", 0))}</b><span>INT</span></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_radar(attributes: dict[str, float]) -> None:
    names = list(ATTRIBUTE_LABELS)
    values = [attributes.get(name, 0) for name in names]
    fig = go.Figure(
        go.Scatterpolar(
            r=values + values[:1],
            theta=names + names[:1],
            fill="toself",
            fillcolor="rgba(34,197,94,0.19)",
            line={"color": "#22c55e", "width": 3},
            marker={"color": "#60a5fa", "size": 7, "line": {"color": "#dbeafe", "width": 1}},
            hovertemplate="%{theta}: %{r:.0f}<extra></extra>",
        )
    )
    fig.update_layout(
        polar={
            "bgcolor": "rgba(15,23,42,0)",
            "radialaxis": {"visible": True, "range": [0, 100], "dtick": 20, "gridcolor": "#334155", "color": "#94a3b8"},
            "angularaxis": {"gridcolor": "#334155", "linecolor": "#475569", "tickfont": {"color": "#dbeafe", "size": 12}},
        },
        paper_bgcolor="rgba(0,0,0,0)",
        font={"color": "#e2e8f0", "family": "Inter"},
        showlegend=False,
        margin={"l": 35, "r": 35, "t": 28, "b": 25},
        height=390,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
