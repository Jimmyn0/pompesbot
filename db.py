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
from typing import Iterable, Optional

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
    PRIMARY KEY (match_id, puuid)
);
CREATE INDEX IF NOT EXISTS games_session ON games(session_id);

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
    return conn


_conn: Optional[sqlite3.Connection] = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = _connect(DB_FILE)
        _migrate_json()
    return _conn


def init(path: Optional[str] = None) -> None:
    """Ouvre la base (chemin alternatif possible, pour les tests)."""
    global _conn
    if _conn is not None:
        _conn.close()
    _conn = _connect(path or DB_FILE)
    if path is None:
        _migrate_json()


# --- Cache KDA ---

def get_cached_kda(puuid: str, queue: int) -> Optional[dict]:
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
            "INSERT OR REPLACE INTO games VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (match_id, r["puuid"], r["name"], session_id, mode, r["champion"],
                 r["kills"], r["deaths"], r["assists"], r["damage"], int(r["win"]), r["pompes"], ended_at)
                for r in results
            ],
        )


def session_leaderboard() -> list[tuple[str, int, int]]:
    """[(pseudo le plus récent, total de pompes, nb de parties)] de la session en cours, du plus chargé au moins chargé."""
    rows = conn().execute(
        """
        SELECT (SELECT g2.name FROM games g2 WHERE g2.puuid = g.puuid ORDER BY g2.ended_at DESC LIMIT 1) AS name,
               SUM(pompes) AS total, COUNT(*) AS n
        FROM games g WHERE session_id = ?
        GROUP BY puuid ORDER BY total DESC
        """,
        (current_session_id(),),
    ).fetchall()
    return [(r["name"], r["total"], r["n"]) for r in rows]


def reset_session() -> None:
    """Clôt la session en cours (l'historique est conservé) ; la suivante démarre à la prochaine partie."""
    conn().execute("UPDATE sessions SET ended_at = ? WHERE ended_at IS NULL", (time.time(),))


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
        FROM owner_teams t WHERE puuid != ''
        GROUP BY puuid HAVING n >= ?
        """,
        (FRIEND_MIN_GAMES,),
    ).fetchall()
    return {r["puuid"]: (r["name"], r["n"]) for r in rows}


# --- Migration depuis les anciens fichiers JSON ---

def _load_json(path: str) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
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
                c.execute("INSERT INTO games VALUES ('MIGRATION', ?, ?, ?, 'report', '—', 0, 0, 0, 0, 0, ?, ?)",
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
