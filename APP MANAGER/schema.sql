CREATE TABLE teams (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    name_key VARCHAR(120) NOT NULL UNIQUE,
    invite_pin_hash VARCHAR(255) NOT NULL,
    logo_data TEXT,
    created_at DATETIME NOT NULL
);

CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'player',
    team_id INTEGER NOT NULL REFERENCES teams(id),
    height_cm INTEGER,
    weight_kg FLOAT,
    preferred_foot VARCHAR(20),
    primary_position VARCHAR(20),
    secondary_position VARCHAR(20),
    photo_url VARCHAR(500),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL
);

CREATE TABLE web_sessions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    expires_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL
);

CREATE TABLE matches (
    id INTEGER PRIMARY KEY,
    team_id INTEGER NOT NULL REFERENCES teams(id),
    opponent VARCHAR(100) NOT NULL,
    played_on DATE NOT NULL,
    kickoff_time TIME,
    venue VARCHAR(150),
    formation VARCHAR(30) NOT NULL DEFAULT '2-3-1',
    status VARCHAR(20) NOT NULL DEFAULT 'scheduled',
    home_score INTEGER,
    away_score INTEGER,
    notes TEXT,
    created_at DATETIME NOT NULL
);

CREATE TABLE match_roster (
    id INTEGER PRIMARY KEY,
    match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES users(id),
    position VARCHAR(20) NOT NULL DEFAULT 'MEI',
    slot INTEGER NOT NULL DEFAULT 0,
    is_starter BOOLEAN NOT NULL DEFAULT TRUE,
    field_x FLOAT,
    field_y FLOAT,
    UNIQUE (match_id, player_id)
);

CREATE TABLE player_stats (
    id INTEGER PRIMARY KEY,
    match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES users(id),
    goals INTEGER NOT NULL DEFAULT 0,
    assists INTEGER NOT NULL DEFAULT 0,
    shots_on_target INTEGER NOT NULL DEFAULT 0,
    tackles INTEGER NOT NULL DEFAULT 0,
    yellow_cards INTEGER NOT NULL DEFAULT 0,
    red_cards INTEGER NOT NULL DEFAULT 0,
    coach_rating FLOAT,
    UNIQUE (match_id, player_id)
);

CREATE TABLE goals (
    id INTEGER PRIMARY KEY,
    match_id INTEGER REFERENCES matches(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES users(id),
    description VARCHAR(250) NOT NULL,
    target_value INTEGER NOT NULL DEFAULT 1,
    progress INTEGER NOT NULL DEFAULT 0,
    completed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME NOT NULL
);

CREATE TABLE ratings (
    id INTEGER PRIMARY KEY,
    match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    rater_id INTEGER NOT NULL REFERENCES users(id),
    rated_player_id INTEGER NOT NULL REFERENCES users(id),
    score FLOAT NOT NULL CHECK (score >= 0 AND score <= 5),
    created_at DATETIME NOT NULL,
    UNIQUE (match_id, rater_id, rated_player_id),
    CHECK (rater_id <> rated_player_id)
);
