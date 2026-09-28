"""
Persistance SQLite : cache KDA, historique des parties, sessions, état de détection.

sqlite3 (bibliothèque standard) suffit : les requêtes portent sur quelques lignes d'un
fichier local et prennent moins d'une milliseconde, sans bloquer la boucle Discord.
Au premier lancement, les anciens fichiers JSON sont importés puis renommés en *.migrated.
"""

import json
import logging
import os
import sqlite3
import time
from collections.abc import Iterable

from config import (
    CACHE_FILE,
    DB_FILE,
    FRIEND_LOOKBACK,
    FRIEND_MIN_GAMES,
    KDA_CACHE_TTL,
    SESSION_FILE,
    STATE_FILE,
)

log = logging.getLogger("PompesBot")

SCHEMA = """
CREATE TABLE IF NOT EXISTS kda_cache (
    puuid TEXT    NOT NULL,
    queue INTEGER NOT NULL,
    name  TEXT    NOT NULL,
    kbar  REAL    NOT NULL,
    abar  REAL    NOT NULL,
    dbar  REAL    NOT NULL,
    ts    REAL    NOT NULL,
    PRIMARY KEY (puuid, queue)
);

CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at REAL NOT NULL,
    ended_at   REAL
);

-- Une ligne par joueur suivi et par partie postée.
CREATE TABLE IF NOT EXISTS games (
    match_id   TEXT    NOT NULL,
    puuid      TEXT    NOT NULL,
    name       TEXT    NOT NULL,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    mode       TEXT    NOT NULL,
    champion   TEXT    NOT NULL,
    kills      INTEGER NOT NULL,
    deaths     INTEGER NOT NULL,
    assists    INTEGER NOT NULL,
    damage     INTEGER NOT NULL,
    win        INTEGER NOT NULL,
    pompes     INTEGER NOT NULL,
    ended_at   REAL    NOT NULL,
    done_at        REAL,            -- date à laquelle le joueur a validé ses pompes
    participant_id INTEGER,         -- numéro du joueur dans la partie (boutons de détail)
    breakdown      TEXT,            -- détail du calcul des pompes (JSON)
    PRIMARY KEY (match_id, puuid)
);
CREATE INDEX IF NOT EXISTS games_session ON games(session_id);
CREATE INDEX IF NOT EXISTS games_puuid   ON games(puuid);

-- Niveau de difficulté choisi par chaque joueur (/difficulte), par PUUID : résiste aux changements de pseudo.
CREATE TABLE IF NOT EXISTS player_levels (
    puuid      TEXT PRIMARY KEY,
    level      TEXT NOT NULL,
    name       TEXT NOT NULL,
    updated_at REAL NOT NULL
);

-- Riot ID (« pseudo#tag » en minuscules) -> PUUID de l'API : chaque joueur n'est demandé à Riot qu'une fois.
CREATE TABLE IF NOT EXISTS riot_ids (
    riot_id TEXT PRIMARY KEY,
    puuid   TEXT NOT NULL
);

-- Succès débloqués (une seule fois par joueur).
CREATE TABLE IF NOT EXISTS achievements (
    puuid       TEXT NOT NULL,
    code        TEXT NOT NULL,
    match_id    TEXT,
    unlocked_at REAL NOT NULL,
    PRIMARY KEY (puuid, code)
);

-- Compte Discord -> joueur LoL (via /lier).
CREATE TABLE IF NOT EXISTS discord_links (
    discord_id INTEGER PRIMARY KEY,
    puuid      TEXT NOT NULL,
    name       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS processed_matches (
    match_id     TEXT PRIMARY KEY,
    processed_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS seeded_puuids (
    puuid TEXT PRIMARY KEY
);

-- Coéquipiers du propriétaire sur ses FRIEND_LOOKBACK dernières parties (détection des potes).
CREATE TABLE IF NOT EXISTS owner_teams (
    match_id    TEXT    NOT NULL,
    match_order INTEGER NOT NULL,
    puuid       TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    PRIMARY KEY (match_id, puuid)
);
"""


def _match_order(match_id: str) -> int:
    """EUW1_7123456789 → 7123456789 (les IDs sont croissants dans le temps)."""
    try:
        return int(match_id.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return 0


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None)  # autocommit ; transactions explicites
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    # Colonnes ajoutées après la création de la table, pour les bases existantes.
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(games)")}
    for column, sql_type in (("done_at", "REAL"), ("participant_id", "INTEGER"), ("breakdown", "TEXT")):
        if column not in existing:
            conn.execute(f"ALTER TABLE games ADD COLUMN {column} {sql_type}")
    return conn


_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = _connect(DB_FILE)
        _migrate_json()
    return _conn


def init(path: str | None = None) -> None:
    """Ouvre la base (chemin alternatif possible, pour les tests)."""
    global _conn
    if _conn is not None:
        _conn.close()
    _conn = _connect(path or DB_FILE)
    if path is None:
        _migrate_json()


# --- Cache KDA ---

def get_cached_kda(puuid: str, queue: int) -> dict | None:
    row = conn().execute(
        "SELECT kbar, abar, dbar, ts FROM kda_cache WHERE puuid = ? AND queue = ?", (puuid, queue)
    ).fetchone()
    if not row or time.time() - row["ts"] > KDA_CACHE_TTL:
        return None
    return {"Kbar": row["kbar"], "Abar": row["abar"], "Dbar": row["dbar"]}


def set_cached_kda(puuid: str, queue: int, kba: dict, player_name: str) -> None:
    conn().execute(
        "INSERT OR REPLACE INTO kda_cache VALUES (?, ?, ?, ?, ?, ?, ?)",
        (puuid, queue, player_name, kba["Kbar"], kba["Abar"], kba["Dbar"], time.time()),
    )


def invalidate_kda(player_name: str) -> bool:
    cur = conn().execute("DELETE FROM kda_cache WHERE lower(name) = lower(?)", (player_name,))
    return cur.rowcount > 0


def kda_player_names() -> list[str]:
    return [r[0] for r in conn().execute("SELECT DISTINCT name FROM kda_cache ORDER BY name")]


# --- Sessions et parties ---

GAME_COLUMNS = ("match_id, puuid, name, session_id, mode, champion, "
                "kills, deaths, assists, damage, win, pompes, ended_at")

# Lignes « report » créées par la migration JSON : comptées dans la session, exclues des stats.
REAL_GAMES = "match_id != 'MIGRATION'"


def current_session_id() -> int:
    c = conn()
    row = c.execute("SELECT id FROM sessions WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
    if row:
        return row["id"]
    return c.execute("INSERT INTO sessions (started_at) VALUES (?)", (time.time(),)).lastrowid


def get_session_total(puuid: str) -> int:
    row = conn().execute(
        "SELECT COALESCE(SUM(pompes), 0) FROM games WHERE session_id = ? AND puuid = ?",
        (current_session_id(), puuid),
    ).fetchone()
    return row[0]


def record_game(match_id: str, mode: str, ended_at: float, results: Iterable[dict]) -> None:
    """Enregistre les résultats d'une partie postée (une transaction)."""
    c = conn()
    session_id = current_session_id()
    with c:
        c.execute("BEGIN")
        c.executemany(
            f"INSERT OR REPLACE INTO games ({GAME_COLUMNS}, participant_id, breakdown) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (match_id, r["puuid"], r["name"], session_id, mode, r["champion"],
                 r["kills"], r["deaths"], r["assists"], r["damage"], int(r["win"]), r["pompes"], ended_at,
                 r.get("pid"), json.dumps(r["breakdown"], ensure_ascii=False) if r.get("breakdown") else None)
                for r in results
            ],
        )


def get_breakdown(match_id: str, participant_id: int) -> dict | None:
    """Pseudo, champion, pompes et détail du calcul d'un joueur sur une partie."""
    row = conn().execute(
        "SELECT name, champion, mode, pompes, breakdown FROM games WHERE match_id = ? AND participant_id = ?",
        (match_id, participant_id),
    ).fetchone()
    if not row or not row["breakdown"]:
        return None
    return {**dict(row), "breakdown": json.loads(row["breakdown"])}


def current_streak(puuid: str) -> tuple[bool | None, int]:
    """Série en cours du joueur dans la session : (victoire ?, longueur), (None, 0) sans partie."""
    rows = conn().execute(
        f"SELECT win FROM games WHERE session_id = ? AND puuid = ? AND {REAL_GAMES} ORDER BY ended_at DESC",
        (current_session_id(), puuid),
    ).fetchall()
    if not rows:
        return None, 0
    first = bool(rows[0]["win"])
    length = 0
    for r in rows:
        if bool(r["win"]) != first:
            break
        length += 1
    return first, length


def done_total(puuid: str) -> int:
    """Pompes validées au total (tous temps)."""
    return conn().execute(
        "SELECT COALESCE(SUM(pompes), 0) FROM games WHERE puuid = ? AND done_at IS NOT NULL", (puuid,)
    ).fetchone()[0]


def season_record(column: str, since: float, exclude_match: str) -> tuple[int, int]:
    """(meilleure valeur de `column` depuis `since`, nb de parties) hors partie `exclude_match`."""
    assert column in ("pompes", "kills", "damage")
    row = conn().execute(
        f"SELECT COALESCE(MAX({column}), 0), COUNT(DISTINCT match_id) FROM games "
        f"WHERE ended_at >= ? AND match_id != ? AND {REAL_GAMES}",
        (since, exclude_match),
    ).fetchone()
    return row[0], row[1]


# --- Succès ---

def unlock(puuid: str, code: str, match_id: str | None = None) -> bool:
    """Débloque un succès ; True si c'est la première fois."""
    cur = conn().execute(
        "INSERT OR IGNORE INTO achievements VALUES (?, ?, ?, ?)", (puuid, code, match_id, time.time())
    )
    return cur.rowcount > 0


def has_achievement(puuid: str, code: str) -> bool:
    return conn().execute(
        "SELECT 1 FROM achievements WHERE puuid = ? AND code = ?", (puuid, code)
    ).fetchone() is not None


def achievements_of(puuid: str) -> list[tuple[str, float]]:
    return [(r["code"], r["unlocked_at"]) for r in conn().execute(
        "SELECT code, unlocked_at FROM achievements WHERE puuid = ? ORDER BY unlocked_at", (puuid,)
    )]


def leaderboard(where: str, params: tuple) -> list[dict]:
    """Classement par joueur, du plus chargé au moins chargé.

    Chaque ligne : name (pseudo le plus récent), total, n (parties), done (pompes validées), avg.
    """
    rows = conn().execute(
        f"""
        SELECT (SELECT g2.name FROM games g2 WHERE g2.puuid = g.puuid ORDER BY g2.ended_at DESC LIMIT 1) AS name,
               SUM(pompes) AS total, COUNT(*) AS n,
               COALESCE(SUM(CASE WHEN done_at IS NOT NULL THEN pompes END), 0) AS done,
               ROUND(AVG(pompes), 1) AS avg
        FROM games g WHERE {where}
        GROUP BY puuid ORDER BY total DESC
        """,
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def session_leaderboard(session_id: int | None = None) -> list[dict]:
    return leaderboard("session_id = ?", (session_id or current_session_id(),))


def session_bounds(session_id: int) -> tuple[float | None, float | None, int]:
    """(fin de la première partie, fin de la dernière, nb de parties) d'une session."""
    row = conn().execute(
        f"SELECT MIN(ended_at), MAX(ended_at), COUNT(DISTINCT match_id) FROM games "
        f"WHERE session_id = ? AND {REAL_GAMES}",
        (session_id,),
    ).fetchone()
    return row[0], row[1], row[2]


def reset_session() -> None:
    """Clôt la session en cours (l'historique est conservé) ; la suivante démarre à la prochaine partie."""
    conn().execute("UPDATE sessions SET ended_at = ? WHERE ended_at IS NULL", (time.time(),))


def rollover_if_idle(ended_at: float, idle_seconds: float) -> int | None:
    """Clôt la session en cours si sa dernière partie date de plus de `idle_seconds` avant `ended_at`.

    Retourne l'id de la session clôturée (pour poster son bilan), sinon None.
    """
    sid = current_session_id()
    last = conn().execute(
        f"SELECT MAX(ended_at) FROM games WHERE session_id = ? AND {REAL_GAMES}", (sid,)
    ).fetchone()[0]
    if last is None or ended_at - last < idle_seconds:
        return None
    conn().execute("UPDATE sessions SET ended_at = ? WHERE id = ?", (last, sid))
    return sid


# --- Pompes faites ---

def mark_done(match_id: str, puuid: str) -> tuple[str, int, str]:
    """Valide les pompes d'un joueur sur une partie.

    Retourne (statut, pompes, pseudo affiché dans l'embed), statut ∈ ok | deja | absent.
    """
    row = conn().execute(
        "SELECT pompes, done_at, name FROM games WHERE match_id = ? AND puuid = ?", (match_id, puuid)
    ).fetchone()
    if row is None:
        return "absent", 0, ""
    if row["done_at"] is not None:
        return "deja", row["pompes"], row["name"]
    conn().execute(
        "UPDATE games SET done_at = ? WHERE match_id = ? AND puuid = ?", (time.time(), match_id, puuid)
    )
    return "ok", row["pompes"], row["name"]


# --- Joueurs et comptes Discord ---

def known_players() -> dict[str, str]:
    """Pseudo le plus récent -> puuid, pour le propriétaire et ses potes uniquement.

    Sources : cache KDA et parties (qui ne concernent que les joueurs suivis), puis les potes
    détectés. Pas owner_teams brut : il contient aussi les inconnus croisés en partie.
    """
    rows: list[tuple[str, str]] = [
        (r["puuid"], r["name"]) for r in conn().execute("SELECT puuid, name FROM kda_cache ORDER BY ts")
    ]
    rows += [(puuid, name) for puuid, (name, _) in known_friends().items()]
    rows += [
        (r["puuid"], r["name"])
        for r in conn().execute(f"SELECT puuid, name FROM games WHERE {REAL_GAMES} ORDER BY ended_at")
    ]
    players: dict[str, str] = {}
    for puuid, name in rows:   # la dernière source l'emporte : pseudo le plus récent
        players = {n: p for n, p in players.items() if p != puuid}
        players[name] = puuid
    return players


def find_player(name: str) -> tuple[str, str] | None:
    """(puuid, pseudo) d'un joueur connu ; recherche insensible à la casse."""
    for n, puuid in known_players().items():
        if n.lower() == name.lower():
            return puuid, n
    return None


def link_discord(discord_id: int, puuid: str, name: str) -> None:
    conn().execute("INSERT OR REPLACE INTO discord_links VALUES (?, ?, ?)", (discord_id, puuid, name))


def linked_player(discord_id: int) -> tuple[str, str] | None:
    row = conn().execute("SELECT puuid, name FROM discord_links WHERE discord_id = ?", (discord_id,)).fetchone()
    return (row["puuid"], row["name"]) if row else None


# --- Statistiques ---

def player_stats(puuid: str) -> dict | None:
    c = conn()
    base = f"FROM games WHERE puuid = ? AND {REAL_GAMES}"
    row = c.execute(
        f"""SELECT COUNT(*) AS n, SUM(pompes) AS total, ROUND(AVG(pompes), 1) AS avg, SUM(win) AS wins,
                   COALESCE(SUM(CASE WHEN done_at IS NOT NULL THEN pompes END), 0) AS done,
                   SUM(kills) AS k, SUM(deaths) AS d, SUM(assists) AS a {base}""",
        (puuid,),
    ).fetchone()
    if not row["n"]:
        return None
    stats = dict(row)
    stats["name"]  = c.execute(f"SELECT name {base} ORDER BY ended_at DESC LIMIT 1", (puuid,)).fetchone()[0]
    stats["worst"] = dict(c.execute(f"SELECT * {base} ORDER BY pompes DESC, ended_at DESC LIMIT 1", (puuid,)).fetchone())
    stats["best"]  = dict(c.execute(f"SELECT * {base} ORDER BY pompes ASC, ended_at DESC LIMIT 1", (puuid,)).fetchone())
    fav = c.execute(
        f"SELECT champion, COUNT(*) AS n {base} GROUP BY champion ORDER BY n DESC LIMIT 1", (puuid,)
    ).fetchone()
    stats["favorite"] = (fav["champion"], fav["n"])
    cursed = c.execute(
        f"""SELECT champion, ROUND(AVG(pompes), 1) AS avg, COUNT(*) AS n {base}
            GROUP BY champion HAVING n >= 2 ORDER BY avg DESC LIMIT 1""",
        (puuid,),
    ).fetchone()
    stats["cursed"] = (cursed["champion"], cursed["avg"], cursed["n"]) if cursed else None
    stats["modes"] = {
        r["mode"]: r["n"] for r in c.execute(f"SELECT mode, COUNT(*) AS n {base} GROUP BY mode", (puuid,))
    }
    return stats


def worst_game_since(since: float) -> dict | None:
    row = conn().execute(
        f"SELECT * FROM games WHERE ended_at >= ? AND {REAL_GAMES} ORDER BY pompes DESC LIMIT 1", (since,)
    ).fetchone()
    return dict(row) if row else None


def count_games_since(since: float) -> int:
    return conn().execute(
        f"SELECT COUNT(DISTINCT match_id) FROM games WHERE ended_at >= ? AND {REAL_GAMES}", (since,)
    ).fetchone()[0]


# --- Riot ID -> PUUID ---

def get_cached_puuid(riot_id: str) -> str | None:
    row = conn().execute("SELECT puuid FROM riot_ids WHERE riot_id = ?", (riot_id.lower(),)).fetchone()
    return row[0] if row else None


def set_cached_puuid(riot_id: str, puuid: str) -> None:
    conn().execute("INSERT OR REPLACE INTO riot_ids VALUES (?, ?)", (riot_id.lower(), puuid))


# --- Niveaux de difficulté ---

def get_level(puuid: str) -> str | None:
    row = conn().execute("SELECT level FROM player_levels WHERE puuid = ?", (puuid,)).fetchone()
    return row[0] if row else None


def set_level(puuid: str, level: str, name: str) -> None:
    conn().execute("INSERT OR REPLACE INTO player_levels VALUES (?, ?, ?, ?)", (puuid, level, name, time.time()))


# --- Méta ---

def get_meta(key: str) -> str | None:
    row = conn().execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(key: str, value: str) -> None:
    conn().execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))


# --- État de détection des parties ---

def is_processed(match_id: str) -> bool:
    return conn().execute("SELECT 1 FROM processed_matches WHERE match_id = ?", (match_id,)).fetchone() is not None


def mark_processed(*match_ids: str) -> None:
    now = time.time()
    conn().executemany(
        "INSERT OR IGNORE INTO processed_matches VALUES (?, ?)", [(mid, now) for mid in match_ids]
    )


def is_seeded(puuid: str) -> bool:
    return conn().execute("SELECT 1 FROM seeded_puuids WHERE puuid = ?", (puuid,)).fetchone() is not None


def mark_seeded(puuid: str, match_ids: list[str]) -> None:
    conn().execute("INSERT OR IGNORE INTO seeded_puuids VALUES (?)", (puuid,))
    mark_processed(*match_ids)


# --- Détection des potes ---

def team_appearances(puuid: str) -> int:
    """Nombre de parties récentes où ce joueur était dans l'équipe du propriétaire."""
    return conn().execute(
        "SELECT COUNT(DISTINCT match_id) FROM owner_teams WHERE puuid = ?", (puuid,)
    ).fetchone()[0]


def rename_team_member(old_puuid: str, new_puuid: str) -> None:
    """Remplace un identifiant provisoire (« lcu:… ») par le PUUID de l'API dans la fenêtre des équipes."""
    c = conn()
    with c:
        c.execute("BEGIN")
        c.execute("UPDATE OR IGNORE owner_teams SET puuid = ? WHERE puuid = ?", (new_puuid, old_puuid))
        c.execute("DELETE FROM owner_teams WHERE puuid = ?", (old_puuid,))


def record_team(match_id: str, teammates: dict[str, str]) -> None:
    """Mémorise les coéquipiers du propriétaire sur une partie (fenêtre glissante)."""
    c = conn()
    order = _match_order(match_id)
    with c:
        c.execute("BEGIN")
        c.execute("DELETE FROM owner_teams WHERE match_id = ?", (match_id,))
        if teammates:
            c.executemany(
                "INSERT INTO owner_teams VALUES (?, ?, ?, ?)",
                [(match_id, order, puuid, name) for puuid, name in teammates.items()],
            )
        else:
            # Ligne témoin : la partie compte dans la fenêtre même sans coéquipier.
            c.execute("INSERT INTO owner_teams VALUES (?, ?, '', '')", (match_id, order))
        c.execute(
            """
            DELETE FROM owner_teams WHERE match_order < (
                SELECT MIN(match_order) FROM (
                    SELECT DISTINCT match_order FROM owner_teams ORDER BY match_order DESC LIMIT ?
                )
            )
            """,
            (FRIEND_LOOKBACK,),
        )


def is_friend(puuid: str) -> bool:
    row = conn().execute(
        "SELECT COUNT(DISTINCT match_id) FROM owner_teams WHERE puuid = ?", (puuid,)
    ).fetchone()
    return bool(puuid) and row[0] >= FRIEND_MIN_GAMES


def known_friends() -> dict[str, tuple[str, int]]:
    """puuid -> (pseudo le plus récent, nb de parties ensemble)."""
    rows = conn().execute(
        """
        SELECT puuid,
               (SELECT t2.name FROM owner_teams t2 WHERE t2.puuid = t.puuid ORDER BY t2.match_order DESC LIMIT 1) AS name,
               COUNT(DISTINCT match_id) AS n
        FROM owner_teams t WHERE puuid != '' AND puuid NOT LIKE 'lcu:%'
        GROUP BY puuid HAVING n >= ?
        """,
        (FRIEND_MIN_GAMES,),
    ).fetchall()
    return {r["puuid"]: (r["name"], r["n"]) for r in rows}


# --- Migration depuis les anciens fichiers JSON ---

def _load_json(path: str) -> dict | None:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _migrate_json() -> None:
    kda, session, state = _load_json(CACHE_FILE), _load_json(SESSION_FILE), _load_json(STATE_FILE)
    if kda is None and session is None and state is None:
        return

    c = _conn
    with c:
        c.execute("BEGIN")
        for key, v in (kda or {}).items():
            if "|" in key and "name" in v:   # ancien format indexé par pseudo : ignoré
                puuid, queue = key.split("|", 1)
                c.execute("INSERT OR REPLACE INTO kda_cache VALUES (?, ?, ?, ?, ?, ?, ?)",
                          (puuid, int(queue), v["name"], v["Kbar"], v["Abar"], v["Dbar"], v["ts"]))

        if session:
            # Les totaux JSON n'ont pas de PUUID : une ligne « report » par joueur dans la session en cours.
            sid = c.execute("INSERT INTO sessions (started_at) VALUES (?)", (time.time(),)).lastrowid
            for name, total in session.items():
                c.execute(f"INSERT INTO games ({GAME_COLUMNS}) "
                          "VALUES ('MIGRATION', ?, ?, ?, 'report', '—', 0, 0, 0, 0, 0, ?, ?)",
                          (f"legacy:{name}", name, sid, total, time.time()))

        state = state or {}
        c.executemany("INSERT OR IGNORE INTO seeded_puuids VALUES (?)",
                      [(p,) for p in state.get("seeded_puuids", [])])
        c.executemany("INSERT OR IGNORE INTO processed_matches VALUES (?, ?)",
                      [(m, time.time()) for m in state.get("processed_match_ids", [])])
        for mid, team in state.get("recent_teams", {}).items():
            rows = [(mid, _match_order(mid), p, n) for p, n in team.items()] or [(mid, _match_order(mid), "", "")]
            c.executemany("INSERT OR IGNORE INTO owner_teams VALUES (?, ?, ?, ?)", rows)

    for path in (CACHE_FILE, SESSION_FILE, STATE_FILE):
        if os.path.exists(path):
            os.replace(path, f"{path}.migrated")
    log.info("Anciens fichiers JSON importés dans la base SQLite (renommés en *.migrated)")
