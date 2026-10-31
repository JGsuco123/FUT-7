"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const screens = Object.fromEntries($$(".screen").map((screen) => [screen.id.replace("screen-", ""), screen]));
const navTabs = $$(".nav-tab");
const authViews = $$("[data-auth-view]");
const benchCard = $("[data-bench-card]");
const starterCard = benchCard.cloneNode(true);
starterCard.classList.remove("bench-player-card");
starterCard.classList.add("starter-player-card");
starterCard.removeAttribute("data-bench-card");
starterCard.setAttribute("aria-label", "Card do jogador titular");
$(".pitch-stage .field-wrap").append(starterCard);

const attributeKeys = ["ata", "def", "for", "vel", "tec", "int"];
const positionOptions = ["GOL", "ZAG", "ALA", "MEI", "ATA"];

let currentUser = null;
let currentData = null;
let currentMatchId = null;
let editingMatchId = null;
let pendingPlayer = null;
let selectedTeamId = "";
let pinnedCard = false;
let cardHideTimer;
let dismissedPlayerKey = "";
let starters = [];
let reserves = [];
let selectedLineupPlayerId = null;

function currentRole() {
  return currentUser?.role || "";
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && currentUser) {
      currentUser = null;
      currentData = null;
      updateSignedOut();
    }
    throw new Error(result.error || "Não foi possível concluir a solicitação.");
  }
  return result;
}

function showScreen(screenName) {
  const requested = screens[screenName] ? screenName : "dashboard";
  const restricted = screens[requested].hasAttribute("data-coach-only") && currentRole() !== "coach";
  const selected = restricted ? "dashboard" : requested;
  const activeTab = navTabs.find((tab) => tab.dataset.screen === selected);
  $(".game-nav").hidden = selected === "auth";
  $(".app-shell").classList.toggle("is-auth-screen", selected === "auth");
  Object.entries(screens).forEach(([name, screen]) => {
    const active = name === selected;
    screen.hidden = !active;
    screen.classList.toggle("is-active", active);
  });
  navTabs.forEach((tab) => {
    const active = tab === activeTab;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
  });
  closePlayerCard();
  if (selected !== "auth") window.scrollTo({ top: 0, behavior: "smooth" });
}

function setAuthView(name) {
  authViews.forEach((view) => { view.hidden = view.dataset.authView !== name; });
}

function setAuthMode(mode) {
  $$("[data-auth-mode]").forEach((tab) => {
    const active = tab.dataset.authMode === mode;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  setAuthView(mode);
  if (mode === "register") setFeedback("[data-register-feedback]", "");
}

function setFeedback(selector, message, isError = false) {
  const element = $(selector);
  if (!element) return;
  element.textContent = message;
  element.classList.toggle("is-error", isError);
}

function setBusy(form, busy) {
  const button = form.querySelector('[type="submit"]');
  if (button) button.disabled = busy;
  form.setAttribute("aria-busy", String(busy));
}

function initials(name) {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0] || "").join("").toUpperCase();
}

function updateSignedOut(message = "") {
  currentUser = null;
  currentData = null;
  $("[data-open-screen='auth']").hidden = false;
  $("[data-logout]").hidden = true;
  $("[data-team-name]").textContent = "CLUB//MODE";
  $("[data-coach-name]").textContent = "ACESSO AO TIME";
  $("[data-team-crest]").replaceChildren(document.createTextNode("F7"));
  $("[data-user-avatar]").textContent = "US";
  $$("[data-coach-only]").forEach((element) => { element.hidden = true; });
  setAuthMode("login");
  showScreen("auth");
  if (message) setFeedback("[data-login-feedback]", message, true);
}

function updateSignedIn(user) {
  currentUser = user;
  $("[data-open-screen='auth']").hidden = true;
  $("[data-logout]").hidden = false;
  $("[data-team-name]").textContent = user.team.name;
  $("[data-coach-name]").textContent = user.role === "coach" ? user.name : `JOGADOR · ${user.name}`;
  $("[data-user-avatar]").textContent = initials(user.name) || "US";
  const crest = $("[data-team-crest]");
  crest.replaceChildren();
  if (user.team.logo) {
    const image = new Image();
    image.src = user.team.logo;
    image.alt = `Escudo do time ${user.team.name}`;
    crest.append(image);
  } else {
    crest.textContent = initials(user.team.name).slice(0, 3) || "F7";
  }
  $$("[data-coach-only]").forEach((element) => {
    element.hidden = user.role !== "coach";
  });
  $$("[data-role-content]").forEach((element) => {
    element.hidden = element.dataset.roleContent !== user.role;
  });
  $("[data-profile-title]").innerHTML = user.role === "coach"
    ? "PERFIL <span>&amp; RESULTADOS</span>"
    : "SEU <span>PERFIL</span>";
}

async function refreshSession(preferredMatchId = null) {
  currentData = await api("/api/me");
  updateSignedIn(currentData.user);
  renderMatches(preferredMatchId);
  renderPlayers();
  renderProfile();
  renderClubSummary();
}

async function loadTeams() {
  const teams = await api("/api/teams");
  renderTeamCatalog(teams);
}

function renderTeamCatalog(teams = []) {
  const catalog = $("[data-team-catalog]");
  const teamSelect = $("[data-player-team]");
  if (!catalog || !teamSelect) return;
  catalog.replaceChildren();
  teamSelect.replaceChildren(new Option("SELECIONE O TIME", ""));
  $("[data-team-count]").textContent = `${String(teams.length).padStart(2, "0")} ${teams.length === 1 ? "TIME" : "TIMES"}`;
  if (!teams.length) {
    const empty = document.createElement("p");
    empty.className = "team-catalog-empty";
    empty.textContent = "AINDA NÃO HÁ TIMES CADASTRADOS.";
    catalog.append(empty);
    return;
  }
  teams.forEach((team) => {
    teamSelect.add(new Option(team.name, team.id));
    const button = document.createElement("button");
    button.type = "button";
    button.className = `team-catalog-item${String(team.id) === selectedTeamId ? " is-selected" : ""}`;
    button.setAttribute("aria-label", `Selecionar time ${team.name}`);
    const crest = document.createElement("span");
    crest.className = "team-catalog-crest";
    if (team.logo) {
      const image = new Image();
      image.src = team.logo;
      image.alt = "";
      crest.append(image);
    } else {
      crest.textContent = initials(team.name).slice(0, 3);
    }
    const name = document.createElement("strong");
    name.textContent = team.name;
    button.append(crest, name);
    button.addEventListener("click", () => {
      selectedTeamId = String(team.id);
      teamSelect.value = selectedTeamId;
      renderTeamCatalog(teams);
      setFeedback("[data-login-feedback]", `TIME SELECIONADO: ${team.name}. ENTRE COM SEU E-MAIL E SENHA.`);
    });
    catalog.append(button);
  });
  if (selectedTeamId) teamSelect.value = selectedTeamId;
}

function fileAsDataUrl(file) {
  if (!file) return Promise.resolve(null);
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(String(reader.result)));
    reader.addEventListener("error", () => reject(new Error("Não foi possível ler o arquivo do escudo.")));
    reader.readAsDataURL(file);
  });
}

function setPlayerProfile(user) {
  if (!user || user.role !== "player" || !user.player) return;
  const player = user.player;
  const form = $("#player-form");
  form.elements.name.value = user.name;
  form.elements.alias.value = user.name;
  form.elements.height.value = player.height_cm || "";
  form.elements.weight.value = player.weight_kg || "";
  form.elements.foot.value = (player.preferred_foot || "").toUpperCase();
  form.elements.position.value = player.position;
  const secondary = form.elements.secondaryPosition;
  if (secondary) secondary.value = player.secondary_position || "";
  form.querySelectorAll("input, select, button[type='submit']").forEach((input) => { input.disabled = true; });
  form.querySelector("[type='submit']").hidden = true;
}

function updateRadar(values = [0, 0, 0, 0, 0, 0]) {
  const center = { x: 150, y: 128 };
  const radius = 95;
  const points = values.map((value, index) => {
    const angle = (-90 + index * 60) * Math.PI / 180;
    return { x: center.x + Math.cos(angle) * radius * value / 100, y: center.y + Math.sin(angle) * radius * value / 100 };
  });
  $("[data-radar-area]").setAttribute("points", points.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" "));
  $("[data-radar-dots]").replaceChildren(...points.map((point) => {
    const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    dot.setAttribute("cx", point.x.toFixed(1));
    dot.setAttribute("cy", point.y.toFixed(1));
    dot.setAttribute("r", "3");
    return dot;
  }));
  attributeKeys.forEach((key, index) => {
    const value = Number(values[index] || 0);
    $(`[data-attribute-value="${key}"]`).textContent = String(value);
    $(`[data-attribute-score="${key}"]`).textContent = String(value);
    $(`[data-attribute-bar="${key}"]`).style.width = `${value}%`;
  });
}

function renderProfile() {
  const user = currentData?.user;
  if (!user) return;
  if (user.role === "coach") {
    const identity = $(".coach-identity");
    identity.querySelector("h3").textContent = user.name;
    identity.querySelector("p").textContent = `${user.team.name} · TEMPORADA ${new Date().getFullYear()}`;
    identity.querySelector(".coach-portrait").textContent = initials(user.name);
    return;
  }
  const player = user.player;
  setPlayerProfile(user);
  $("[data-card-name]").textContent = user.name;
  $("[data-card-position]").textContent = player.position;
  $("[data-card-country]").textContent = (player.preferred_foot || "FUT7").slice(0, 3).toUpperCase();
  const overall = String(player.overall);
  $("[data-card-overall]").textContent = overall;
  $("[data-overall-summary]").textContent = overall;
  $(".preview-overall small").textContent = "ATRIBUTOS CALCULADOS · 50% TREINADOR + 50% TIME";
  attributeKeys.forEach((key, index) => {
    $(`[data-attribute-value="${key}"]`).textContent = String(player.attributes[index]);
  });
  updateRadar(player.attributes);
  $("[data-profile-rating-summary]").textContent = "NOTA FINAL: 50% TREINADOR + 50% AVALIAÇÃO DO TIME";
}

function matchOptionLabel(match) {
  const dateLabel = new Date(`${match.played_on}T12:00:00`).toLocaleDateString("pt-BR");
  const timeLabel = match.kickoff_time ? ` às ${match.kickoff_time}` : "";
  const score = match.status === "played" && match.home_score !== null && match.away_score !== null
    ? ` · ${match.home_score}–${match.away_score}`
    : "";
  return `${dateLabel}${timeLabel} · ${match.opponent}${score}`;
}

function renderMatches(preferredMatchId = null) {
  const matches = currentData?.matches || [];
  const selector = $("[data-match-select]");
  selector.replaceChildren(new Option("SELECIONE UMA PARTIDA", ""));
  matches.forEach((match) => selector.add(new Option(matchOptionLabel(match), String(match.id))));
  const upcoming = currentData?.upcoming_match_id;
  const wanted = preferredMatchId ?? (matches.some((match) => match.id === currentMatchId) ? currentMatchId : upcoming);
  const selected = matches.find((match) => String(match.id) === String(wanted))
    || matches[0]
    || null;
  currentMatchId = selected?.id ?? null;
  selector.value = selected ? String(selected.id) : "";
  $("[data-edit-match]").disabled = !selected || selected.status === "played";
  $("[data-record-result]").disabled = !selected || !selected.roster.length;
  const resultButton = $("[data-record-result]");
  resultButton.replaceChildren(
    document.createTextNode(selected?.status === "played" ? "ATUALIZAR RESULTADO " : "REGISTRAR RESULTADO "),
    document.createTextNode(selected?.status === "played" ? "↗" : "＋"),
  );
  $("[data-result-form]").hidden = true;
  $("[data-match-status]").hidden = true;
  setFeedback("[data-match-status]", "");
  renderLineup(selected);
  const nextMatch = matches.find((match) => String(match.id) === String(currentData?.upcoming_match_id))
    || [...matches].reverse().find((match) => match.status === "scheduled");
  const latestPlayed = matches.find((match) => match.status === "played");
  const nextTitle = $(".next-game-tile strong");
  const nextTile = $(".next-game-tile small");
  if (nextMatch) {
    nextTitle.textContent = "PRÓXIMO JOGO";
    nextTile.textContent = `${new Date(`${nextMatch.played_on}T12:00:00`).toLocaleDateString("pt-BR")}${nextMatch.kickoff_time ? ` às ${nextMatch.kickoff_time}` : ""} · ${nextMatch.opponent}`;
  } else if (latestPlayed) {
    nextTitle.textContent = "ÚLTIMO JOGO";
    nextTile.textContent = `${latestPlayed.opponent} · ${latestPlayed.home_score}–${latestPlayed.away_score}`;
  } else {
    nextTitle.textContent = "PRÓXIMO JOGO";
    nextTile.textContent = "NENHUMA PARTIDA CADASTRADA";
  }
}

function openResultEditor(match) {
  if (currentRole() !== "coach" || !match?.roster.length) return;
  const form = $("[data-result-form]");
  form.reset();
  form.hidden = false;
  $("[data-result-form-title]").textContent = match.status === "played"
    ? `ATUALIZAR RESULTADO · ${match.opponent}`
    : `REGISTRAR RESULTADO · ${match.opponent}`;
  $("[data-result-team]").textContent = currentData.user.team.name;
  $("[data-result-opponent]").textContent = match.opponent;
  form.elements.home_score.value = match.home_score ?? "";
  form.elements.away_score.value = match.away_score ?? "";
  const tbody = $("[data-result-players]");
  tbody.replaceChildren();
  const statFields = [
    ["goals", "GOLS"],
    ["assists", "ASSISTÊNCIAS"],
    ["yellow_cards", "CARTÕES AMARELOS"],
    ["red_cards", "CARTÕES VERMELHOS"],
  ];
  match.roster.forEach((player) => {
    const row = document.createElement("tr");
    const name = document.createElement("td");
    name.className = "result-player-name";
    name.textContent = player.name;
    row.append(name);
    statFields.forEach(([field, label]) => {
      const cell = document.createElement("td");
      const input = document.createElement("input");
      input.type = "number";
      input.name = field;
      input.min = "0";
      input.max = "99";
      input.step = "1";
      input.required = true;
      input.value = String(player.match_stats[field] || 0);
      input.setAttribute("aria-label", `${label} de ${player.name}`);
      cell.append(input);
      row.append(cell);
    });
    row.dataset.playerId = String(player.id);
    tbody.append(row);
  });
  setFeedback("[data-result-feedback]", "");
  form.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function groupForPosition(position) {
  if (position === "ATA" || position === "GOL" || position === "ZAG") return position;
  return "MID";
}

function fallbackFieldPosition(player, index, lineup) {
  const group = groupForPosition(player.roster_position);
  const groupPlayers = lineup.filter((item) => groupForPosition(item.roster_position) === group);
  const groupIndex = groupPlayers.indexOf(player);
  const yByGroup = { ATA: 17, MID: 39, ZAG: 62, GOL: 82 };
  return {
    x: (100 * (groupIndex + 1)) / (groupPlayers.length + 1),
    y: yByGroup[group] ?? 50,
  };
}

function pitchPlayer(player, index) {
  const button = document.createElement("div");
  button.className = "pitch-player";
  button.dataset.starterPlayer = String(index);
  const fallback = fallbackFieldPosition(player, index, starters);
  button.style.setProperty("--x", `${player.field_x ?? fallback.x}%`);
  button.style.setProperty("--y", `${player.field_y ?? fallback.y}%`);
  button.setAttribute("role", "button");
  button.tabIndex = 0;
  button.setAttribute("aria-label", `Ver card de ${player.name}`);
  const disc = document.createElement("span");
  disc.className = `player-disc${player.roster_position === "GOL" ? " keeper-disc" : ""}`;
  const initialsLabel = document.createElement("b");
  initialsLabel.textContent = initials(player.name);
  disc.append(initialsLabel);
  const rating = document.createElement("b");
  rating.className = "player-rating";
  rating.textContent = String(player.overall);
  const name = document.createElement("span");
  name.className = "player-name";
  name.textContent = player.name;
  button.append(disc, rating, name);
  return button;
}

function renderLineup(match) {
  const pitch = $("[data-pitch-players]").closest(".pitch");
  const playersLayer = $("[data-pitch-players]");
  const resultBadge = $("[data-match-result]");
  playersLayer.replaceChildren();
  const roster = match?.roster || [];
  starters = roster.filter((player) => player.is_starter);
  reserves = roster.filter((player) => !player.is_starter);
  starters.forEach((player, index) => playersLayer.append(pitchPlayer(player, index)));
  if (!starters.length) {
    const empty = document.createElement("span");
    empty.className = "pitch-empty-label";
    empty.textContent = match ? "SEM TITULARES" : "ESCALAÇÃO NÃO CADASTRADA";
    playersLayer.append(empty);
  }
  renderBench();
  $("[data-lineup-count]").textContent = `${starters.length} TITULARES`;
  $("[data-starter-count]").textContent = `${starters.length} TITULARES`;
  const formation = match?.formation || "LIVRE";
  $("#lineup-title").innerHTML = `ESCALAÇÃO <span>— ${formation}</span>`;
  const hasResult = match?.status === "played" && match.home_score !== null && match.away_score !== null;
  resultBadge.hidden = !hasResult;
  resultBadge.textContent = hasResult ? `RESULTADO ${match.home_score}–${match.away_score}` : "";
  pitch.setAttribute("aria-label", match
    ? `Escalação da partida contra ${match.opponent}, esquema ${formation}`
    : "Campo de Futebol 7 aguardando uma escalação");
}

function renderBench() {
  const list = $("[data-bench-list]");
  list.replaceChildren();
  $(".bench-heading b").innerHTML = `${reserves.length} <small>JOGADORES</small>`;
  if (!reserves.length) {
    const empty = document.createElement("p");
    empty.className = "team-catalog-empty";
    empty.textContent = "Nenhuma reserva convocada.";
    list.append(empty);
    return;
  }
  reserves.forEach((player, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "bench-player";
    button.dataset.benchPlayer = String(index);
    button.setAttribute("aria-label", `Ver card de ${player.name}`);
    const number = document.createElement("span");
    number.className = "bench-number";
    number.textContent = String(index + 1).padStart(2, "0");
    const copy = document.createElement("span");
    copy.className = "bench-player-copy";
    const name = document.createElement("b");
    name.textContent = player.name;
    const position = document.createElement("small");
    position.textContent = `${player.roster_position || "LIVRE"} · ${player.overall}`;
    copy.append(name, position);
    const rating = document.createElement("span");
    rating.className = "bench-rating";
    rating.textContent = String(player.overall);
    button.append(number, copy, rating);
    list.append(button);
  });
}

function updatePlayerHoverCard(card, player) {
  const overall = player.overall;
  const points = player.attributes.map((value, index) => {
    const angle = (-90 + index * 60) * Math.PI / 180;
    const radius = 59 * value / 100;
    return `${(90 + Math.cos(angle) * radius).toFixed(1)},${(79 + Math.sin(angle) * radius).toFixed(1)}`;
  }).join(" ");
  card.querySelector("[data-bench-overall]").textContent = String(overall);
  card.querySelector("[data-bench-position]").textContent = player.roster_position || player.position;
  card.querySelector("[data-bench-name]").textContent = player.name;
  card.querySelector("[data-bench-radar-area]").setAttribute("points", points);
  attributeKeys.forEach((key, index) => {
    card.querySelector(`[data-bench-attribute="${key}"]`).textContent = String(player.attributes[index]);
  });
  card.querySelector(".bench-card-avatar").textContent = initials(player.name);
  card.hidden = false;
}

function openPlayerCard(type, index, pin = false) {
  const isBench = type === "bench";
  const card = isBench ? benchCard : starterCard;
  const player = (isBench ? reserves : starters)[index];
  if (!player) return;
  window.clearTimeout(cardHideTimer);
  if (pin) pinnedCard = true;
  benchCard.classList.toggle("is-pinned", isBench && pinnedCard);
  starterCard.classList.toggle("is-pinned", !isBench && pinnedCard);
  $$(".bench-player, .pitch-player").forEach((button) => {
    const selected = button.dataset.benchPlayer !== undefined
      ? isBench && Number(button.dataset.benchPlayer) === index
      : !isBench && Number(button.dataset.starterPlayer) === index;
    button.classList.toggle("is-selected", selected);
    button.setAttribute("aria-expanded", String(selected));
  });
  benchCard.hidden = !isBench;
  starterCard.hidden = isBench;
  updatePlayerHoverCard(card, player);
}

function closePlayerCard() {
  window.clearTimeout(cardHideTimer);
  pinnedCard = false;
  benchCard.classList.remove("is-pinned");
  starterCard.classList.remove("is-pinned");
  benchCard.hidden = true;
  starterCard.hidden = true;
  $$(".bench-player, .pitch-player").forEach((button) => {
    button.classList.remove("is-selected");
    button.setAttribute("aria-expanded", "false");
  });
}

function scheduleCardClose() {
  window.clearTimeout(cardHideTimer);
  cardHideTimer = window.setTimeout(() => {
    if (!pinnedCard) closePlayerCard();
  }, 180);
}

function renderPlayers() {
  const players = currentData?.players || [];
  const tbody = $("#screen-players .game-table tbody");
  tbody.replaceChildren();
  $(".screen#screen-players .section-meta b").textContent = `${players.length} JOGADORES`;
  $("#screen-players .table-note").textContent = "DADOS DO ELENCO";
  if (!players.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 10;
    cell.textContent = "Nenhum jogador cadastrado neste time.";
    row.append(cell);
    tbody.append(row);
    return;
  }
  players.forEach((player) => {
    const row = document.createElement("tr");
    const name = document.createElement("td");
    const avatar = document.createElement("span");
    avatar.className = "table-avatar";
    avatar.textContent = initials(player.name);
    name.append(avatar, document.createTextNode(` ${player.name}`));
    const stats = player.stats;
    const average = stats.coach_rating !== null && stats.peer_rating !== null
      ? ((stats.coach_rating + stats.peer_rating) / 2).toFixed(2)
      : "—";
    [name, player.position, stats.games, stats.goals, stats.assists, stats.yellow_cards, stats.red_cards, stats.tackles, average, player.overall].forEach((value) => {
      if (value === name) {
        row.append(name);
      } else {
        const cell = document.createElement("td");
        cell.textContent = String(value);
        row.append(cell);
      }
    });
    row.tabIndex = 0;
    row.setAttribute("role", "button");
    row.setAttribute("aria-label", `Ver resumo de ${player.name}`);
    row.addEventListener("click", () => renderPlayerDetail(player));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        renderPlayerDetail(player);
      }
    });
    tbody.append(row);
  });
}

function renderPlayerDetail(player) {
  const stats = player.stats;
  $(".players-detail-grid article:first-child h3").textContent = player.name;
  const firstDetails = $(".players-detail-grid article:first-child .detail-stat-row");
  firstDetails.replaceChildren();
  [
    ["GOLS", stats.goals],
    ["ASSISTÊNCIAS", stats.assists],
    ["AMARELOS", stats.yellow_cards],
    ["VERMELHOS", stats.red_cards],
    ["JOGOS", stats.games],
  ].forEach(([label, value]) => {
    const item = document.createElement("span");
    const strong = document.createElement("b");
    item.append(document.createTextNode(`${label} `), strong);
    strong.textContent = String(value);
    firstDetails.append(item);
  });
  const average = stats.coach_rating !== null && stats.peer_rating !== null
    ? ((stats.coach_rating + stats.peer_rating) / 2).toFixed(2)
    : "—";
  $(".players-detail-grid article:last-child h3").textContent = `NOTA ${average}`;
  const lastDetails = $(".players-detail-grid article:last-child .detail-stat-row");
  lastDetails.replaceChildren();
  [["MÉDIA DO TIME", stats.peer_rating ?? "—"], ["NOTA DO TREINADOR", stats.coach_rating ?? "—"]].forEach(([label, value]) => {
    const item = document.createElement("span");
    const strong = document.createElement("b");
    item.append(document.createTextNode(`${label} `), strong);
    strong.textContent = String(value);
    lastDetails.append(item);
  });
}

function renderClubSummary() {
  if (!currentData) return;
  const playedMatches = currentData.matches
    .filter((match) => match.status === "played" && match.home_score !== null && match.away_score !== null)
    .sort((first, second) => first.played_on.localeCompare(second.played_on));
  const wins = playedMatches.filter((match) => match.home_score > match.away_score).length;
  const draws = playedMatches.filter((match) => match.home_score === match.away_score).length;
  const goalsFor = playedMatches.reduce((total, match) => total + match.home_score, 0);
  const goalsAgainst = playedMatches.reduce((total, match) => total + match.away_score, 0);
  $("[data-club-match-count]").textContent = String(playedMatches.length);
  const counts = [
    playedMatches.length,
    playedMatches.length ? `${Math.round(wins / playedMatches.length * 100)}%` : "—",
    goalsFor,
    currentData.players.length,
  ];
  $$(".club-stat-card strong").forEach((element, index) => { element.textContent = String(counts[index] ?? "—"); });
  const recordValues = $$(".club-record .record-row b");
  if (recordValues.length >= 4) {
    recordValues[0].textContent = String(goalsFor);
    recordValues[1].textContent = String(goalsAgainst);
    recordValues[2].textContent = "—";
    const finalRatings = currentData.players
      .filter((player) => player.stats.coach_rating !== null && player.stats.peer_rating !== null)
      .map((player) => (player.stats.coach_rating + player.stats.peer_rating) / 2);
    recordValues[3].textContent = finalRatings.length
      ? (finalRatings.reduce((sum, rating) => sum + rating, 0) / finalRatings.length).toFixed(2)
      : "—";
  }
  const resultPlaceholder = $(".club-record .result-placeholder b");
  if (resultPlaceholder) resultPlaceholder.textContent = `${wins}V · ${draws}E · ${playedMatches.length - wins - draws}D`;
  const coachMetrics = $$(".coach-results .metric-strip strong");
  if (coachMetrics.length) coachMetrics[0].textContent = String(playedMatches.length);
  const chart = $(".club-chart");
  chart.setAttribute("aria-label", `${playedMatches.length} partidas com resultado registrado no time`);
  chart.querySelector(".chart-bars").replaceChildren();
  const recentMatches = playedMatches.slice(-6);
  const maxGoals = Math.max(1, ...recentMatches.map((match) => match.home_score));
  recentMatches.forEach((match) => {
    const bar = document.createElement("div");
    const value = document.createElement("i");
    if (match.home_score > match.away_score) value.classList.add("bar-win");
    value.style.setProperty("--bar", `${Math.max(12, match.home_score / maxGoals * 88)}%`);
    const label = document.createElement("span");
    label.textContent = match.opponent.slice(0, 10).toUpperCase();
    bar.append(value, label);
    chart.querySelector(".chart-bars").append(bar);
  });
}

function rosterPickerRow(player, selected = null) {
  const row = document.createElement("div");
  row.className = "roster-picker-row";
  row.dataset.playerId = String(player.id);
  if (selected?.field_x !== null && selected?.field_x !== undefined) {
    row.dataset.fieldX = String(selected.field_x);
    row.dataset.fieldY = String(selected.field_y);
  }
  const identity = document.createElement("span");
  identity.className = "roster-picker-name";
  identity.textContent = player.name;
  const position = document.createElement("small");
  position.textContent = player.position;
  identity.append(position);
  const role = document.createElement("select");
  role.setAttribute("aria-label", `Função de ${player.name} na escalação`);
  [["", "FORA DA CONVOCAÇÃO"], ["starter", "TITULAR"], ["reserve", "RESERVA"]].forEach(([value, label]) => {
    role.add(new Option(label, value));
  });
  role.value = selected ? (selected.is_starter ? "starter" : "reserve") : "";
  const positionSelect = document.createElement("select");
  positionSelect.setAttribute("aria-label", `Posição de ${player.name} na escalação`);
  positionSelect.add(new Option("LIVRE", ""));
  positionOptions.forEach((value) => positionSelect.add(new Option(value, value)));
  positionSelect.value = selected?.roster_position || "";
  positionSelect.disabled = !role.value;
  positionSelect.className = "roster-picker-position";
  role.classList.add("roster-picker-role");
  const placeButton = document.createElement("button");
  placeButton.type = "button";
  placeButton.className = "roster-map-button";
  placeButton.textContent = "MAPA";
  placeButton.setAttribute("aria-label", `Selecionar ${player.name} para posicionar no campo`);
  placeButton.disabled = role.value !== "starter";
  role.addEventListener("change", () => {
    positionSelect.disabled = !role.value;
    placeButton.disabled = role.value !== "starter";
    if (role.value !== "starter") {
      delete row.dataset.fieldX;
      delete row.dataset.fieldY;
      if (selectedLineupPlayerId === player.id) selectedLineupPlayerId = null;
    } else if (row.dataset.fieldX === undefined) {
      const starterRows = $$(".roster-picker-row", $("[data-roster-picker]"))
        .filter((item) => item.querySelector(".roster-picker-role").value === "starter");
      const location = defaultFieldPosition(starterRows.indexOf(row), starterRows.length);
      row.dataset.fieldX = String(location.x);
      row.dataset.fieldY = String(location.y);
    }
    renderLineupEditorPitch();
  });
  placeButton.addEventListener("click", () => selectLineupPlayer(player.id));
  row.append(identity, role, positionSelect, placeButton);
  return row;
}

function defaultFieldPosition(index, total) {
  const columns = Math.max(1, Math.min(4, Math.ceil(Math.sqrt(total))));
  const rows = Math.ceil(total / columns);
  const column = index % columns;
  const row = Math.floor(index / columns);
  return {
    x: columns === 1 ? 50 : 18 + (column * 64) / (columns - 1),
    y: rows === 1 ? 50 : 16 + (row * 68) / (rows - 1),
  };
}

function renderLineupEditorPitch() {
  const pitch = $("[data-lineup-editor-pitch]");
  const layer = $("[data-editor-pitch-players]");
  if (!pitch || !layer) return;
  layer.replaceChildren();
  const rows = $$(".roster-picker-row", $("[data-roster-picker]"))
    .filter((row) => row.querySelector(".roster-picker-role").value === "starter");
  rows.forEach((row, index) => {
    const player = currentData.players.find((item) => item.id === Number(row.dataset.playerId));
    if (!player) return;
    const marker = document.createElement("button");
    marker.type = "button";
    marker.className = "pitch-player pitch-editor-player";
    marker.dataset.editorMarker = row.dataset.playerId;
    const fallback = defaultFieldPosition(index, rows.length);
    marker.style.setProperty("--x", `${row.dataset.fieldX ?? fallback.x}%`);
    marker.style.setProperty("--y", `${row.dataset.fieldY ?? fallback.y}%`);
    marker.classList.toggle("is-map-selected", selectedLineupPlayerId === Number(row.dataset.playerId));
    marker.setAttribute("aria-label", `Selecionar ${player.name} para reposicionar no campo`);
    const disc = document.createElement("span");
    disc.className = `player-disc${row.querySelector(".roster-picker-position").value === "GOL" ? " keeper-disc" : ""}`;
    const initialsLabel = document.createElement("b");
    initialsLabel.textContent = initials(player.name);
    disc.append(initialsLabel);
    const name = document.createElement("span");
    name.className = "player-name";
    name.textContent = player.name;
    marker.append(disc, name);
    layer.append(marker);
  });
}

function selectLineupPlayer(playerId) {
  const row = $$(".roster-picker-row", $("[data-roster-picker]"))
    .find((item) => Number(item.dataset.playerId) === Number(playerId));
  if (!row || row.querySelector(".roster-picker-role").value !== "starter") {
    setFeedback("[data-lineup-map-feedback]", "MARQUE O ATLETA COMO TITULAR ANTES DE POSICIONÁ-LO.");
    return;
  }
  selectedLineupPlayerId = Number(playerId);
  const player = currentData.players.find((item) => item.id === selectedLineupPlayerId);
  setFeedback("[data-lineup-map-feedback]", `${player.name.toUpperCase()} SELECIONADO · TOQUE NO CAMPO PARA POSICIONAR.`);
  renderLineupEditorPitch();
}

function positionSelectedLineupPlayer(event) {
  const marker = event.target.closest("[data-editor-marker]");
  if (marker) {
    selectLineupPlayer(marker.dataset.editorMarker);
    return;
  }
  if (selectedLineupPlayerId === null) {
    setFeedback("[data-lineup-map-feedback]", "SELECIONE UM TITULAR EM MAPA ANTES DE TOCAR NO CAMPO.");
    return;
  }
  const row = $$(".roster-picker-row", $("[data-roster-picker]"))
    .find((item) => Number(item.dataset.playerId) === selectedLineupPlayerId);
  if (!row || row.querySelector(".roster-picker-role").value !== "starter") {
    selectedLineupPlayerId = null;
    renderLineupEditorPitch();
    return;
  }
  const pitch = $("[data-lineup-editor-pitch]");
  const bounds = pitch.getBoundingClientRect();
  const x = Math.max(8, Math.min(92, ((event.clientX - bounds.left) / bounds.width) * 100));
  const y = Math.max(8, Math.min(92, ((event.clientY - bounds.top) / bounds.height) * 100));
  row.dataset.fieldX = String(Number(x.toFixed(1)));
  row.dataset.fieldY = String(Number(y.toFixed(1)));
  const player = currentData.players.find((item) => item.id === selectedLineupPlayerId);
  setFeedback("[data-lineup-map-feedback]", `${player.name.toUpperCase()} POSICIONADO NO CAMPO.`);
  renderLineupEditorPitch();
}

function nudgeSelectedLineupPlayer(deltaX, deltaY) {
  if (selectedLineupPlayerId === null) return;
  const row = $$(".roster-picker-row", $("[data-roster-picker]"))
    .find((item) => Number(item.dataset.playerId) === selectedLineupPlayerId);
  if (!row || row.querySelector(".roster-picker-role").value !== "starter") return;
  const current = {
    x: Number(row.dataset.fieldX ?? 50),
    y: Number(row.dataset.fieldY ?? 50),
  };
  row.dataset.fieldX = String(Math.max(8, Math.min(92, current.x + deltaX)));
  row.dataset.fieldY = String(Math.max(8, Math.min(92, current.y + deltaY)));
  renderLineupEditorPitch();
}

function openMatchEditor(match = null) {
  if (currentRole() !== "coach") return;
  selectedLineupPlayerId = null;
  editingMatchId = match?.id ?? null;
  const form = $("[data-match-form]");
  form.reset();
  form.hidden = false;
  $("[data-match-form-title]").textContent = match ? "EDITAR PARTIDA E ESCALAÇÃO" : "NOVA PARTIDA";
  const today = new Date();
  const localToday = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  form.elements.played_on.value = match?.played_on || localToday;
  form.elements.kickoff_time.value = match?.kickoff_time || "";
  form.elements.opponent.value = match?.opponent || "";
  form.elements.venue.value = match?.venue || "";
  form.elements.formation.value = match?.formation || "Livre";
  const rosterById = new Map((match?.roster || []).map((player) => [player.id, player]));
  const picker = $("[data-roster-picker]");
  picker.replaceChildren();
  const players = currentData?.players || [];
  if (!players.length) {
    const message = document.createElement("p");
    message.className = "team-catalog-empty";
    message.textContent = "Nenhum jogador cadastrado. Compartilhe o nome do time e o PIN para formar o elenco.";
    picker.append(message);
  } else {
    players.forEach((player) => picker.append(rosterPickerRow(player, rosterById.get(player.id))));
  }
  const starterRows = $$(".roster-picker-row", picker)
    .filter((row) => row.querySelector(".roster-picker-role").value === "starter");
  starterRows.forEach((row, index) => {
    if (row.dataset.fieldX === undefined || row.dataset.fieldY === undefined) {
      const location = defaultFieldPosition(index, starterRows.length);
      row.dataset.fieldX = String(location.x);
      row.dataset.fieldY = String(location.y);
    }
  });
  renderLineupEditorPitch();
  setFeedback("[data-lineup-map-feedback]", "NENHUM TITULAR SELECIONADO PARA POSICIONAR.");
  setFeedback("[data-match-feedback]", "");
  form.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function matchRosterFromForm() {
  return $$(".roster-picker-row", $("[data-roster-picker]"))
    .filter((row) => row.querySelector(".roster-picker-role").value)
    .map((row) => {
      const isStarter = row.querySelector(".roster-picker-role").value === "starter";
      const entry = {
        player_id: Number(row.dataset.playerId),
        is_starter: isStarter,
        position: row.querySelector(".roster-picker-position").value,
      };
      if (isStarter && row.dataset.fieldX !== undefined && row.dataset.fieldY !== undefined) {
        entry.field_x = Number(row.dataset.fieldX);
        entry.field_y = Number(row.dataset.fieldY);
      }
      return entry;
    });
}

function wireForms() {
  const lineupPitch = $("[data-lineup-editor-pitch]");
  lineupPitch.addEventListener("click", positionSelectedLineupPlayer);
  lineupPitch.addEventListener("keydown", (event) => {
    const movement = {
      ArrowLeft: [-2, 0],
      ArrowRight: [2, 0],
      ArrowUp: [0, -2],
      ArrowDown: [0, 2],
    }[event.key];
    if (!movement) return;
    event.preventDefault();
    nudgeSelectedLineupPlayer(...movement);
  });

  $("[data-login-form]").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy(form, true);
    setFeedback("[data-login-feedback]", "");
    try {
      const data = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email: form.elements.email.value, password: form.elements.password.value }),
      });
      form.reset();
      await refreshSession();
      showScreen("dashboard");
    } catch (error) {
      setFeedback("[data-login-feedback]", error.message, true);
    } finally {
      setBusy(form, false);
    }
  });

  $("[data-coach-form]").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const pin = form.elements.pin.value;
    if (pin !== form.elements.pinConfirm.value) {
      setFeedback("[data-coach-feedback]", "OS PINs NÃO COINCIDEM.", true);
      return;
    }
    setBusy(form, true);
    try {
      const logo = await fileAsDataUrl(form.elements.logo.files[0]);
      const data = await api("/api/auth/register/coach", {
        method: "POST",
        body: JSON.stringify({
          name: form.elements.coachName.value,
          email: form.elements.email.value,
          password: form.elements.password.value,
          team_name: form.elements.teamName.value,
          pin,
          logo,
        }),
      });
      form.reset();
      await refreshSession();
      showScreen("dashboard");
      setFeedback("[data-match-feedback]", "TIME CRIADO. COMPARTILHE O NOME DO TIME E O PIN COM OS JOGADORES.");
      await loadTeams();
    } catch (error) {
      setFeedback("[data-coach-feedback]", error.message, true);
    } finally {
      setBusy(form, false);
    }
  });

  $("[data-player-account-form]").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    if (form.elements.password.value !== form.elements.passwordConfirm.value) {
      setFeedback("[data-player-account-feedback]", "AS SENHAS NÃO COINCIDEM.", true);
      return;
    }
    pendingPlayer = {
      name: form.elements.name.value.trim(),
      email: form.elements.email.value.trim(),
      password: form.elements.password.value,
    };
    setFeedback("[data-player-account-feedback]", "");
    setAuthView("player-profile");
  });

  $("[data-player-profile-form]").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!pendingPlayer) {
      setFeedback("[data-player-profile-feedback]", "REINICIE O CADASTRO DO JOGADOR.", true);
      setAuthView("player-account");
      return;
    }
    pendingPlayer.profile = {
      height_cm: Number(form.elements.height.value),
      weight_kg: Number(form.elements.weight.value),
      position: form.elements.position.value,
      secondary_position: form.elements.secondaryPosition.value,
      preferred_foot: form.elements.preferredFoot.value,
    };
    setFeedback("[data-player-profile-feedback]", "");
    loadTeams().then(() => setAuthView("player-invite")).catch((error) => {
      setFeedback("[data-player-profile-feedback]", error.message, true);
    });
  });

  $("[data-player-invite-form]").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!pendingPlayer) {
      setFeedback("[data-player-invite-feedback]", "REINICIE O CADASTRO DO JOGADOR.", true);
      setAuthView("player-account");
      return;
    }
    setBusy(form, true);
    try {
      await api("/api/auth/register/player", {
        method: "POST",
        body: JSON.stringify({
          ...pendingPlayer,
          ...pendingPlayer.profile,
          team_id: Number(form.elements.team.value),
          pin: form.elements.pin.value,
        }),
      });
      pendingPlayer = null;
      form.reset();
      await refreshSession();
      showScreen("dashboard");
    } catch (error) {
      setFeedback("[data-player-invite-feedback]", error.message, true);
    } finally {
      setBusy(form, false);
    }
  });

  $("[data-match-form]").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const roster = matchRosterFromForm();
    const payload = {
      opponent: form.elements.opponent.value,
      played_on: form.elements.played_on.value,
      kickoff_time: form.elements.kickoff_time.value,
      venue: form.elements.venue.value,
      formation: form.elements.formation.value,
      roster,
    };
    setBusy(form, true);
    setFeedback("[data-match-feedback]", "");
    try {
      const path = editingMatchId
        ? `/api/matches/${editingMatchId}/lineup`
        : "/api/matches";
      const result = await api(path, { method: editingMatchId ? "PUT" : "POST", body: JSON.stringify(payload) });
      form.hidden = true;
      await refreshSession(result.match.id);
      $("[data-match-status]").hidden = false;
      setFeedback("[data-match-status]", "PARTIDA E ESCALAÇÃO SALVAS.");
    } catch (error) {
      setFeedback("[data-match-feedback]", error.message, true);
    } finally {
      setBusy(form, false);
    }
  });

  $("[data-result-form]").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const stats = $$("tr", $("[data-result-players]")).map((row) => {
      const values = Object.fromEntries([...row.querySelectorAll("input")].map((input) => [input.name, Number(input.value)]));
      return { player_id: Number(row.dataset.playerId), ...values };
    });
    setBusy(form, true);
    setFeedback("[data-result-feedback]", "");
    try {
      const result = await api(`/api/matches/${currentMatchId}/result`, {
        method: "PUT",
        body: JSON.stringify({
          home_score: form.elements.home_score.valueAsNumber,
          away_score: form.elements.away_score.valueAsNumber,
          stats,
        }),
      });
      form.hidden = true;
      await refreshSession(result.match.id);
      $("[data-match-status]").hidden = false;
      setFeedback("[data-match-status]", "RESULTADO E ESTATÍSTICAS SALVOS.");
    } catch (error) {
      setFeedback("[data-result-feedback]", error.message, true);
    } finally {
      setBusy(form, false);
    }
  });
}

function setStarRating(group, value) {
  const options = $$(".star-rating-option", group);
  const rating = Math.max(0, Math.min(5, value));
  options.forEach((option, index) => {
    const filled = index < rating;
    option.classList.toggle("is-filled", filled);
    option.setAttribute("aria-checked", String(rating > 0 && index === rating - 1));
    option.tabIndex = index === (rating > 0 ? rating - 1 : 0) ? 0 : -1;
  });
  $("[data-rating-input]", group).value = String(rating);
}

function wireStarRatings() {
  $$(".star-rating").forEach((group) => {
    group.addEventListener("click", (event) => {
      const option = event.target.closest(".star-rating-option");
      if (!option) return;
      const selected = Number(option.dataset.ratingValue);
      const current = Number($("[data-rating-input]", group).value);
      setStarRating(group, current === selected ? 0 : selected);
    });
    group.addEventListener("keydown", (event) => {
      const option = event.target.closest(".star-rating-option");
      if (!option) return;
      const current = Number($("[data-rating-input]", group).value);
      const keyDeltas = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 };
      let next = current;
      if (event.key in keyDeltas) next = Math.max(0, Math.min(5, current + keyDeltas[event.key]));
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = 5;
      else return;
      event.preventDefault();
      setStarRating(group, next);
      const focusIndex = next > 0 ? next - 1 : 0;
      $$(".star-rating-option", group)[focusIndex].focus();
    });
  });
}

function wireNavigation() {
  navTabs.forEach((tab) => {
    tab.addEventListener("click", () => showScreen(tab.dataset.screen));
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      const visibleTabs = navTabs.filter((item) => !item.hidden);
      const index = visibleTabs.indexOf(tab);
      const next = visibleTabs[(index + (event.key === "ArrowRight" ? 1 : -1) + visibleTabs.length) % visibleTabs.length];
      next.focus();
      showScreen(next.dataset.screen);
    });
  });
  $$("[data-open-screen]").forEach((button) => button.addEventListener("click", () => showScreen(button.dataset.openScreen)));
  $$("[data-auth-mode]").forEach((tab) => tab.addEventListener("click", () => setAuthMode(tab.dataset.authMode)));
  $$("[data-register-role]").forEach((button) => button.addEventListener("click", () => {
    setFeedback("[data-register-feedback]", "");
    setAuthView(button.dataset.registerRole === "coach" ? "coach" : "player-account");
  }));
  $$("[data-auth-back]").forEach((button) => button.addEventListener("click", () => setAuthView("register")));
  $$("[data-auth-step-back]").forEach((button) => button.addEventListener("click", () => setAuthView(button.dataset.authStepBack)));
  $("[data-no-team]").addEventListener("click", () => {
    setAuthMode("login");
    setFeedback("[data-login-feedback]", "PEÇA O NOME DO TIME E O PIN AO TREINADOR PARA CRIAR SUA CONTA.");
  });
  $("[data-logout]").addEventListener("click", async () => {
    try {
      await api("/api/auth/logout", { method: "POST", body: "{}" });
      updateSignedOut();
    } catch (error) {
      setFeedback("[data-login-feedback]", error.message, true);
    }
  });
  $("[data-match-select]").addEventListener("change", (event) => {
    const match = currentData.matches.find((item) => String(item.id) === event.target.value);
    renderMatches(match?.id ?? null);
  });
  $("[data-new-match]").addEventListener("click", () => openMatchEditor());
  $("[data-next-match-action]").addEventListener("click", () => {
    showScreen("dashboard");
    openMatchEditor();
  });
  $("[data-edit-match]").addEventListener("click", () => {
    const match = currentData.matches.find((item) => item.id === currentMatchId);
    if (match) openMatchEditor(match);
  });
  $("[data-record-result]").addEventListener("click", () => {
    const match = currentData.matches.find((item) => item.id === currentMatchId);
    if (match) openResultEditor(match);
  });
  $("[data-cancel-match]").addEventListener("click", () => { $("[data-match-form]").hidden = true; });
  $("[data-cancel-result]").addEventListener("click", () => { $("[data-result-form]").hidden = true; });
}

function wirePlayerCards() {
  document.addEventListener("pointerover", (event) => {
    const target = event.target.closest("[data-bench-player], [data-starter-player]");
    if (!target || target.contains(event.relatedTarget)) return;
    const isBench = target.dataset.benchPlayer !== undefined;
    const index = Number(isBench ? target.dataset.benchPlayer : target.dataset.starterPlayer);
    const key = `${isBench ? "bench" : "starter"}-${index}`;
    if (dismissedPlayerKey !== key) openPlayerCard(isBench ? "bench" : "starter", index);
  });
  document.addEventListener("pointerout", (event) => {
    const target = event.target.closest("[data-bench-player], [data-starter-player]");
    if (!target || target.contains(event.relatedTarget)) return;
    scheduleCardClose();
  });
  document.addEventListener("focusin", (event) => {
    const target = event.target.closest("[data-bench-player], [data-starter-player]");
    if (!target) return;
    const isBench = target.dataset.benchPlayer !== undefined;
    openPlayerCard(isBench ? "bench" : "starter", Number(isBench ? target.dataset.benchPlayer : target.dataset.starterPlayer));
  });
  document.addEventListener("click", (event) => {
    const target = event.target.closest("[data-bench-player], [data-starter-player]");
    if (!target) {
      if (!event.target.closest(".bench-panel, .field-wrap")) closePlayerCard();
      return;
    }
    const isBench = target.dataset.benchPlayer !== undefined;
    const index = Number(isBench ? target.dataset.benchPlayer : target.dataset.starterPlayer);
    const key = `${isBench ? "bench" : "starter"}-${index}`;
    dismissedPlayerKey = "";
    if (pinnedCard && target.classList.contains("is-selected")) closePlayerCard();
    else openPlayerCard(isBench ? "bench" : "starter", index, true);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closePlayerCard();
    const target = event.target.closest("[data-bench-player], [data-starter-player]");
    if (target && ["Enter", " "].includes(event.key)) {
      event.preventDefault();
      target.click();
    }
  });
  [benchCard, starterCard].forEach((card) => {
    card.addEventListener("pointerenter", () => window.clearTimeout(cardHideTimer));
    card.addEventListener("pointerleave", scheduleCardClose);
    card.querySelector("[data-close-bench-card]").addEventListener("click", closePlayerCard);
  });
}

async function boot() {
  wireNavigation();
  wireForms();
  wireStarRatings();
  wirePlayerCards();
  setAuthMode("login");
  try {
    const data = await api("/api/auth/session");
    if (!data.authenticated) {
      updateSignedOut();
    } else {
      currentData = data;
      updateSignedIn(data.user);
      renderMatches();
      renderPlayers();
      renderProfile();
      renderClubSummary();
      showScreen("dashboard");
    }
  } catch (error) {
    updateSignedOut();
    setFeedback("[data-login-feedback]", error.message === "Entre na sua conta para continuar."
      ? ""
      : `${error.message} Inicie o servidor web para usar o aplicativo.`, error.message !== "Entre na sua conta para continuar.");
  }
  loadTeams().catch((error) => {
    setFeedback("[data-login-feedback]", `Não foi possível carregar os times: ${error.message}`, true);
  });
}

boot();
