-- =====================================================================
--  ATHLYTICS — schéma de la base de données
--  SQLite 3.35+ / conçu pour l'analyse longitudinale d'athlètes
--
--  Conventions :
--    * toutes les dates "civiles" sont des TEXT 'YYYY-MM-DD'
--    * tous les instants sont des TEXT ISO-8601 UTC 'YYYY-MM-DDTHH:MM:SSZ'
--    * les durées sont en secondes, les distances en mètres,
--      les vitesses en m/s, les puissances en watts.
--  Toute unité qui déroge à cette règle est suffixée dans le nom
--  de la colonne (ex. weight_kg, height_cm, pace_s_per_km).
-- =====================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- teams
CREATE TABLE IF NOT EXISTS teams (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    sport       TEXT,
    coach       TEXT,
    season      TEXT,
    color       TEXT DEFAULT '#4f8ff7',
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- ------------------------------------------------------------- athletes
CREATE TABLE IF NOT EXISTS athletes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name    TEXT NOT NULL,
    last_name     TEXT NOT NULL,
    sex           TEXT CHECK (sex IN ('M','F','X')) DEFAULT 'X',
    birth_date    TEXT,
    height_cm     REAL,
    weight_kg     REAL,
    primary_sport TEXT DEFAULT 'running',
    discipline    TEXT,           -- ex. "10 km / semi", "triathlon LD", "route"
    level         TEXT,           -- loisir | compétiteur | national | élite | pro
    team_id       INTEGER REFERENCES teams(id) ON DELETE SET NULL,
    email         TEXT,
    phone         TEXT,
    country       TEXT,
    accent        TEXT DEFAULT '#4f8ff7',   -- couleur d'identification dans l'UI
    status        TEXT DEFAULT 'active' CHECK (status IN ('active','injured','paused','archived')),
    joined_at     TEXT,
    notes         TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_athletes_team   ON athletes(team_id);
CREATE INDEX IF NOT EXISTS idx_athletes_status ON athletes(status);

-- --------------------------------------------------- profils physiologiques
-- Historisés : chaque test/mise à jour crée une nouvelle ligne datée.
-- Le profil "courant" est celui de effective_date maximale <= date demandée.
CREATE TABLE IF NOT EXISTS physiology (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id          INTEGER NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
    effective_date      TEXT NOT NULL,
    weight_kg           REAL,
    body_fat_pct        REAL,
    muscle_mass_kg      REAL,
    hr_max              INTEGER,      -- FC maximale mesurée
    hr_rest             INTEGER,      -- FC de repos
    hr_lt1              INTEGER,      -- FC au premier seuil (SV1 / LT1)
    hr_lt2              INTEGER,      -- FC au second seuil (SV2 / LT2 / LTHR)
    vo2max              REAL,         -- ml/kg/min
    vvo2max             REAL,         -- m/s, vitesse associée à VO2max (VMA)
    ftp_w               REAL,         -- Functional Threshold Power
    cp_w                REAL,         -- Critical Power
    w_prime_j           REAL,         -- W' (réserve anaérobie), joules
    pmax_w              REAL,         -- puissance maximale (sprint)
    threshold_pace_s_km REAL,         -- allure au seuil, s/km
    critical_speed_ms   REAL,         -- vitesse critique, m/s
    d_prime_m           REAL,         -- D' (équivalent distance de W')
    vdot                REAL,         -- VDOT Daniels
    running_economy     REAL,         -- ml/kg/km
    lactate_threshold_mmol REAL,
    max_hr_source       TEXT,         -- test | terrain | estimation | montre
    source              TEXT,         -- laboratoire | terrain | montre | déclaratif
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_physio_athlete ON physiology(athlete_id, effective_date DESC);

-- ------------------------------------------------------------- zones
CREATE TABLE IF NOT EXISTS zone_models (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id  INTEGER NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('hr','power','pace')),
    model       TEXT NOT NULL,   -- coggan | friel_lthr | seiler3 | polarized5 | karvonen | custom
    basis       TEXT,            -- lthr | hrmax | hrr | ftp | cp | threshold_pace
    basis_value REAL,
    effective_date TEXT NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_zonemodels ON zone_models(athlete_id, kind, is_active);

CREATE TABLE IF NOT EXISTS zones (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    zone_model_id INTEGER NOT NULL REFERENCES zone_models(id) ON DELETE CASCADE,
    idx           INTEGER NOT NULL,          -- 1..n
    name          TEXT NOT NULL,
    short_name    TEXT,
    low           REAL,                      -- borne basse (unité selon kind)
    high          REAL,                      -- borne haute (NULL = infini)
    low_pct       REAL,
    high_pct      REAL,
    color         TEXT,
    purpose       TEXT,                      -- objectif physiologique
    UNIQUE (zone_model_id, idx)
);

-- ------------------------------------------- comptes fournisseurs & montres
CREATE TABLE IF NOT EXISTS provider_accounts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id       INTEGER NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
    provider         TEXT NOT NULL CHECK (provider IN ('garmin','polar','coros','manual','demo')),
    provider_user_id TEXT,
    access_token     TEXT,
    refresh_token    TEXT,
    token_secret     TEXT,          -- OAuth 1.0a (Garmin)
    token_type       TEXT,
    scope            TEXT,
    expires_at       TEXT,
    status           TEXT NOT NULL DEFAULT 'disconnected'
                     CHECK (status IN ('connected','expired','error','disconnected','pending')),
    last_sync_at     TEXT,
    last_error       TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (athlete_id, provider)
);

CREATE TABLE IF NOT EXISTS devices (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id    INTEGER NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
    provider      TEXT NOT NULL,
    external_id   TEXT,
    name          TEXT,
    model         TEXT,
    manufacturer  TEXT,
    kind          TEXT,          -- montre | ceinture | capteur puissance | home-trainer
    firmware      TEXT,
    battery_pct   INTEGER,
    last_seen_at  TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (athlete_id, provider, external_id)
);

CREATE TABLE IF NOT EXISTS oauth_states (
    state       TEXT PRIMARY KEY,
    provider    TEXT NOT NULL,
    athlete_id  INTEGER,
    verifier    TEXT,         -- PKCE code_verifier ou OAuth1 token secret temporaire
    request_token TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS sync_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    provider    TEXT NOT NULL,
    athlete_id  INTEGER REFERENCES athletes(id) ON DELETE CASCADE,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,      -- running | ok | partial | error
    imported    INTEGER DEFAULT 0,
    skipped     INTEGER DEFAULT 0,
    failed      INTEGER DEFAULT 0,
    message     TEXT,
    detail      TEXT
);
CREATE INDEX IF NOT EXISTS idx_synclog ON sync_log(athlete_id, started_at DESC);

-- ---------------------------------------------------------- activités
CREATE TABLE IF NOT EXISTS activities (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id        INTEGER NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
    provider          TEXT NOT NULL DEFAULT 'manual',
    external_id       TEXT,
    source_file       TEXT,
    sport             TEXT NOT NULL,          -- running | cycling | swimming | ...
    sub_sport         TEXT,                   -- trail | piste | home-trainer | ...
    name              TEXT,
    start_time        TEXT NOT NULL,          -- ISO UTC
    local_date        TEXT NOT NULL,          -- 'YYYY-MM-DD' locale athlète
    timezone          TEXT DEFAULT 'Europe/Paris',
    duration_s        REAL NOT NULL,          -- durée écoulée
    moving_time_s     REAL,
    distance_m        REAL,
    elevation_gain_m  REAL,
    elevation_loss_m  REAL,
    avg_hr            REAL,
    max_hr            REAL,
    hrr60             REAL,      -- récupération FC à 60 s post-effort (bpm)
    avg_power_w       REAL,
    max_power_w       REAL,
    np_w              REAL,      -- Normalized Power / puissance normalisée
    xpower_w          REAL,      -- xPower (Skiba)
    intensity_factor  REAL,      -- IF = NP / FTP
    variability_index REAL,      -- VI = NP / Pmoy
    work_kj           REAL,
    avg_speed_ms      REAL,
    max_speed_ms      REAL,
    gap_pace_s_km     REAL,      -- allure ajustée à la pente
    ngp_s_km          REAL,      -- Normalized Graded Pace
    avg_cadence       REAL,
    max_cadence       REAL,
    avg_stride_len_m  REAL,
    avg_gct_ms        REAL,      -- ground contact time
    avg_vert_osc_cm   REAL,
    avg_vert_ratio    REAL,
    avg_temp_c        REAL,
    calories          REAL,
    tss               REAL,      -- Training Stress Score (puissance)
    hrtss             REAL,      -- TSS estimé depuis la FC
    rtss              REAL,      -- running TSS
    stss              REAL,      -- swim TSS
    load              REAL,      -- charge retenue (meilleure estimation disponible)
    load_source       TEXT,      -- tss | rtss | hrtss | stss | rpe
    trimp_banister    REAL,
    trimp_edwards     REAL,
    trimp_lucia       REAL,
    session_rpe       REAL,      -- RPE × durée (min)
    rpe               INTEGER,   -- 1..10
    feel              INTEGER,   -- 1..5 ressenti
    aerobic_te        REAL,      -- Training Effect aérobie (Firstbeat/Garmin)
    anaerobic_te      REAL,
    epoc_ml_kg        REAL,
    vo2max_est        REAL,
    decoupling_pct    REAL,      -- Pw:HR ou Pa:HR drift
    efficiency_factor REAL,      -- NP/FCmoy ou vitesse/FCmoy
    aerobic_decoupling_valid INTEGER DEFAULT 0,
    polarization_index REAL,
    elevation_min_m   REAL,
    elevation_max_m   REAL,
    start_lat         REAL,
    start_lon         REAL,
    has_streams       INTEGER NOT NULL DEFAULT 0,
    has_gps           INTEGER NOT NULL DEFAULT 0,
    device_name       TEXT,
    weather           TEXT,
    notes             TEXT,
    tags              TEXT,      -- CSV libre
    planned_id        INTEGER,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (athlete_id, provider, external_id)
);
CREATE INDEX IF NOT EXISTS idx_act_athlete_date ON activities(athlete_id, local_date DESC);
CREATE INDEX IF NOT EXISTS idx_act_start        ON activities(start_time DESC);
CREATE INDEX IF NOT EXISTS idx_act_sport        ON activities(sport);

-- Flux temporels : un enregistrement par (activité, série), JSON zlib-compressé.
CREATE TABLE IF NOT EXISTS activity_streams (
    activity_id  INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,   -- time|hr|power|speed|cadence|altitude|lat|lon|temp|distance|...
    sample_rate  REAL NOT NULL DEFAULT 1,
    n_samples    INTEGER NOT NULL,
    encoding     TEXT NOT NULL DEFAULT 'zlib+json',
    data         BLOB NOT NULL,
    PRIMARY KEY (activity_id, kind)
);

CREATE TABLE IF NOT EXISTS activity_laps (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id   INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    idx           INTEGER NOT NULL,
    label         TEXT,
    start_offset_s REAL,
    duration_s    REAL,
    distance_m    REAL,
    avg_hr        REAL,
    max_hr        REAL,
    avg_power_w   REAL,
    np_w          REAL,
    avg_speed_ms  REAL,
    avg_cadence   REAL,
    elevation_gain_m REAL,
    intensity     TEXT,     -- work | rest | warmup | cooldown
    UNIQUE (activity_id, idx)
);

CREATE TABLE IF NOT EXISTS activity_zone_time (
    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,      -- hr | power | pace
    zone_idx    INTEGER NOT NULL,
    seconds     REAL NOT NULL,
    PRIMARY KEY (activity_id, kind, zone_idx)
);

-- Courbe des meilleures performances (Mean Maximal Power / Pace / HR)
CREATE TABLE IF NOT EXISTS best_efforts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id    INTEGER NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
    activity_id   INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    local_date    TEXT NOT NULL,
    sport         TEXT NOT NULL,
    kind          TEXT NOT NULL,     -- power | speed | hr
    duration_s    INTEGER NOT NULL,
    value         REAL NOT NULL,     -- W, m/s ou bpm
    value_per_kg  REAL,
    start_offset_s REAL
);
CREATE INDEX IF NOT EXISTS idx_best ON best_efforts(athlete_id, kind, duration_s, value DESC);
CREATE INDEX IF NOT EXISTS idx_best_date ON best_efforts(athlete_id, local_date);

-- --------------------------------------------------- bien-être / quotidien
CREATE TABLE IF NOT EXISTS wellness (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id       INTEGER NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
    date             TEXT NOT NULL,
    -- mesures objectives (montre)
    hrv_rmssd        REAL,
    hrv_sdnn         REAL,
    hrv_ln_rmssd     REAL,
    resting_hr       REAL,
    sleep_total_min  REAL,
    sleep_deep_min   REAL,
    sleep_rem_min    REAL,
    sleep_light_min  REAL,
    sleep_awake_min  REAL,
    sleep_score      REAL,
    sleep_onset      TEXT,
    sleep_wake       TEXT,
    spo2_avg         REAL,
    respiration_avg  REAL,
    body_battery_max REAL,
    body_battery_min REAL,
    stress_avg       REAL,
    steps            INTEGER,
    active_kcal      REAL,
    total_kcal       REAL,
    weight_kg        REAL,
    body_fat_pct     REAL,
    hydration_ml     REAL,
    -- déclaratif athlète (échelles Hooper-Mackinnon 1..7, 1 = très bon)
    soreness         INTEGER,
    fatigue          INTEGER,
    mood             INTEGER,
    stress_subj      INTEGER,
    sleep_quality    INTEGER,
    motivation       INTEGER,
    illness          INTEGER DEFAULT 0,
    menstrual_phase  TEXT,
    -- dérivés
    hooper_index     REAL,
    readiness        REAL,      -- 0..100 calculé
    readiness_flag   TEXT,      -- vert | ambre | rouge
    source           TEXT DEFAULT 'manual',
    notes            TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (athlete_id, date)
);
CREATE INDEX IF NOT EXISTS idx_wellness ON wellness(athlete_id, date DESC);

-- ------------------------------------------------ charge quotidienne agrégée
CREATE TABLE IF NOT EXISTS daily_load (
    athlete_id     INTEGER NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
    date           TEXT NOT NULL,
    load           REAL NOT NULL DEFAULT 0,
    trimp          REAL NOT NULL DEFAULT 0,
    duration_s     REAL NOT NULL DEFAULT 0,
    distance_m     REAL NOT NULL DEFAULT 0,
    elevation_m    REAL NOT NULL DEFAULT 0,
    sessions       INTEGER NOT NULL DEFAULT 0,
    ctl            REAL,      -- Chronic Training Load (fitness), EWMA 42 j
    atl            REAL,      -- Acute Training Load (fatigue), EWMA 7 j
    tsb            REAL,      -- Training Stress Balance (forme) = CTL(j-1) - ATL(j-1)
    ctl_ramp_7d    REAL,      -- variation hebdo de CTL
    acwr_rolling   REAL,      -- ratio aigu:chronique (moyennes glissantes 7:28)
    acwr_ewma      REAL,      -- ratio aigu:chronique (EWMA, Williams 2017)
    monotony       REAL,      -- Foster : moyenne/écart-type de la charge sur 7 j
    strain         REAL,      -- Foster : charge hebdo × monotonie
    z_score_7d     REAL,
    PRIMARY KEY (athlete_id, date)
);

-- --------------------------------------------------------- planification
CREATE TABLE IF NOT EXISTS training_blocks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id  INTEGER NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    phase       TEXT,   -- préparation générale | spécifique | affûtage | compétition | transition
    focus       TEXT,
    start_date  TEXT NOT NULL,
    end_date    TEXT NOT NULL,
    target_ctl  REAL,
    target_weekly_load REAL,
    notes       TEXT
);
CREATE INDEX IF NOT EXISTS idx_blocks ON training_blocks(athlete_id, start_date);

CREATE TABLE IF NOT EXISTS planned_workouts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id     INTEGER NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
    date           TEXT NOT NULL,
    sport          TEXT NOT NULL,
    name           TEXT NOT NULL,
    description    TEXT,
    structure      TEXT,       -- JSON : [{repeat, steps:[{duration, target, zone}]}]
    target_load    REAL,
    target_duration_s REAL,
    target_distance_m REAL,
    intensity      TEXT,       -- récupération | endurance | tempo | seuil | VO2max | neuromusculaire
    status         TEXT NOT NULL DEFAULT 'planned'
                   CHECK (status IN ('planned','completed','missed','moved','cancelled')),
    completed_activity_id INTEGER REFERENCES activities(id) ON DELETE SET NULL,
    compliance_pct REAL,
    coach_notes    TEXT,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_planned ON planned_workouts(athlete_id, date);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id  INTEGER REFERENCES athletes(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    date        TEXT NOT NULL,
    sport       TEXT,
    priority    TEXT CHECK (priority IN ('A','B','C')) DEFAULT 'B',
    location    TEXT,
    distance_m  REAL,
    target_time_s REAL,
    result_time_s REAL,
    result_rank   INTEGER,
    result_notes  TEXT,
    notes       TEXT
);
CREATE INDEX IF NOT EXISTS idx_events ON events(athlete_id, date);

-- ------------------------------------------------------------- tests labo
CREATE TABLE IF NOT EXISTS lab_tests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id  INTEGER NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
    date        TEXT NOT NULL,
    type        TEXT NOT NULL,   -- vo2max | lactate | ftp20 | cp_test | cooper | conconi | dexa | force
    protocol    TEXT,
    lab         TEXT,
    results     TEXT,            -- JSON libre
    conclusion  TEXT,
    notes       TEXT
);
CREATE INDEX IF NOT EXISTS idx_labtests ON lab_tests(athlete_id, date DESC);

CREATE TABLE IF NOT EXISTS lactate_points (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id   INTEGER NOT NULL REFERENCES lab_tests(id) ON DELETE CASCADE,
    stage     INTEGER NOT NULL,
    intensity REAL,        -- W ou m/s selon le protocole
    speed_ms  REAL,
    power_w   REAL,
    hr        REAL,
    lactate   REAL,        -- mmol/L
    vo2       REAL,        -- ml/kg/min
    vco2      REAL,
    rer       REAL,
    rpe       INTEGER
);

-- ------------------------------------------------------ blessures & santé
CREATE TABLE IF NOT EXISTS injuries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id   INTEGER NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
    date         TEXT NOT NULL,
    body_part    TEXT NOT NULL,
    side         TEXT,       -- gauche | droite | bilatéral | n/a
    type         TEXT,       -- tendinopathie | fracture de fatigue | élongation | ...
    mechanism    TEXT,       -- surcharge | traumatique | récidive
    severity     INTEGER,    -- 1..5
    status       TEXT DEFAULT 'ouverte' CHECK (status IN ('ouverte','en rééducation','résolue')),
    days_lost    INTEGER DEFAULT 0,
    return_date  TEXT,
    diagnosis    TEXT,
    treatment    TEXT,
    notes        TEXT
);
CREATE INDEX IF NOT EXISTS idx_injuries ON injuries(athlete_id, date DESC);

-- ------------------------------------------------------------- alertes
CREATE TABLE IF NOT EXISTS alerts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id   INTEGER NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
    date         TEXT NOT NULL,
    code         TEXT NOT NULL,     -- acwr_high | monotony_high | hrv_drop | ramp_high | ...
    severity     TEXT NOT NULL CHECK (severity IN ('info','warning','critical')),
    title        TEXT NOT NULL,
    message      TEXT,
    metric       TEXT,
    value        REAL,
    threshold    REAL,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (athlete_id, date, code)
);
CREATE INDEX IF NOT EXISTS idx_alerts ON alerts(athlete_id, date DESC);

-- ----------------------------------------------------- notes de coaching
CREATE TABLE IF NOT EXISTS coach_notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id INTEGER NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
    date       TEXT NOT NULL,
    author     TEXT DEFAULT 'coach',
    category   TEXT,       -- technique | mental | nutrition | médical | logistique
    text       TEXT NOT NULL,
    pinned     INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_notes ON coach_notes(athlete_id, date DESC);

-- ------------------------------------------------------------ paramètres
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
