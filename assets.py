"""
assets.py — SQLite-backed store for game world data.

Tables
------
crew          : crew member profiles
crew_messages : interaction records linked to a crew member
ships         : vessels that have traveled through the locks
art_assets    : inventory of image files used in campaigns
lock_radio    : VHF radio traffic between vessels and the lock operator

No pygame dependency; safe to import anywhere.
"""

import sqlite3
import os

DB_PATH = os.path.join('saves', 'assets.db')

SCHEMA = """
CREATE TABLE IF NOT EXISTS crew (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    role        TEXT,                        -- deckhand / engineer / captain / cook / etc.
    vessel_name TEXT,                        -- ship they're currently assigned to
    bio         TEXT,                        -- short background blurb
    notes       TEXT                         -- freeform GM notes
);

CREATE TABLE IF NOT EXISTS crew_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    crew_id     INTEGER REFERENCES crew(id), -- NULL = unknown / unregistered sender
    sender      TEXT    NOT NULL,
    role        TEXT,                        -- deckhand / engineer / captain / etc.
    context     TEXT,                        -- what triggered this (e.g. 'barge_connected')
    stage_id    TEXT                         -- operator / deckhand / engineer / captain
);

CREATE TABLE IF NOT EXISTS ships (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT,
    vessel_type TEXT,                        -- kayak / yacht / barge / paddleboat / towboat
    direction   TEXT,                        -- upstream / downstream
    origin      TEXT,
    destination TEXT,
    cargo       TEXT,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS art_assets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    filename    TEXT    NOT NULL UNIQUE,
    category    TEXT,                        -- background / character / ui / boat / environment
    description TEXT,
    tags        TEXT,                        -- comma-separated keywords
    campaign_id TEXT,                        -- NULL = shared across all campaigns
    width       INTEGER,
    height      INTEGER
);

CREATE TABLE IF NOT EXISTS lock_radio (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id   INTEGER NOT NULL,            -- groups a request/reply exchange
    sender_type TEXT    NOT NULL,            -- 'ship' or 'operator'
    sender_name TEXT    NOT NULL,            -- vessel name or operator callsign
    vessel_name TEXT,                        -- ship involved (set even when operator is sender)
    direction   TEXT,                        -- upstream / downstream
    message     TEXT    NOT NULL
);
"""

class GameDatabase:
    """
    Thin wrapper around the assets SQLite database.

    Usage
    -----
        db = GameDatabase()
        pat = db.add_crew('Pat Holloway', role='deckhand', vessel_name='MV Prairie Star')
        db.add_crew_message('Pat', crew_id=pat, context='barge_connected', stage_id='deckhand')
        db.add_ship(name='MV Prairie Star', vessel_type='towboat', direction='downstream')
        db.close()

    Or as a context manager:
        with GameDatabase() as db:
            db.add_lock_radio_message('ship', 'MV Prairie Star', 'Lock 12, this is Prairie Star...')
    """

    def __init__(self, path: str = DB_PATH):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row   # rows behave like dicts
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # ── Context manager ───────────────────────────────────────────────────────

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self._conn.close()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _rows(self, sql: str, params: tuple = ()) -> list[dict]:
        cur = self._conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

    def _run(self, sql: str, params: tuple = ()) -> int:
        """Execute a write statement and return the new row id."""
        cur = self._conn.execute(sql, params)
        self._conn.commit()
        return cur.lastrowid

    # ── Crew ──────────────────────────────────────────────────────────────────

    def add_crew(
        self,
        name:        str,
        *,
        role:        str = None,
        vessel_name: str = None,
        bio:         str = None,
        notes:       str = None,
    ) -> int:
        return self._run(
            """INSERT INTO crew (name, role, vessel_name, bio, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (name, role, vessel_name, bio, notes),
        )

    def get_crew(self, crew_id: int) -> dict | None:
        rows = self._rows("SELECT * FROM crew WHERE id = ?", (crew_id,))
        return rows[0] if rows else None

    def crew_list(self, *, role: str = None, vessel_name: str = None) -> list[dict]:
        clauses, params = [], []
        if role:
            clauses.append("role = ?");         params.append(role)
        if vessel_name:
            clauses.append("vessel_name = ?");  params.append(vessel_name)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return self._rows(f"SELECT * FROM crew {where} ORDER BY name", tuple(params))

    def update_crew(self, crew_id: int, **fields):
        """Update any subset of crew fields by keyword argument."""
        allowed = {'name', 'role', 'vessel_name', 'bio', 'notes'}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        self._run(
            f"UPDATE crew SET {set_clause} WHERE id = ?",
            (*updates.values(), crew_id),
        )

    # ── Crew messages ─────────────────────────────────────────────────────────

    def add_crew_message(
        self,
        sender:   str,
        *,
        crew_id:  int = None,
        role:     str = None,
        context:  str = None,
        stage_id: str = None,
    ) -> int:
        return self._run(
            """INSERT INTO crew_messages (crew_id, sender, role, context, stage_id)
               VALUES (?, ?, ?, ?, ?)""",
            (crew_id, sender, role, context, stage_id),
        )

    def crew_messages(
        self,
        *,
        crew_id:  int = None,
        stage_id: str = None,
        role:     str = None,
        limit:    int = 50,
    ) -> list[dict]:
        clauses, params = [], []
        if crew_id is not None:
            clauses.append("cm.crew_id = ?"); params.append(crew_id)
        if stage_id:
            clauses.append("cm.stage_id = ?"); params.append(stage_id)
        if role:
            clauses.append("cm.role = ?");     params.append(role)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return self._rows(
            f"""SELECT cm.*, c.name AS crew_name, c.vessel_name
                FROM crew_messages cm
                LEFT JOIN crew c ON c.id = cm.crew_id
                {where}
                ORDER BY cm.id DESC LIMIT ?""",
            (*params, limit),
        )

    # ── Ships ─────────────────────────────────────────────────────────────────

    def add_ship(
        self,
        *,
        name:        str = None,
        vessel_type: str = None,
        direction:   str = None,
        origin:      str = None,
        destination: str = None,
        cargo:       str = None,
        notes:       str = None,
    ) -> int:
        return self._run(
            """INSERT INTO ships (name, vessel_type, direction, origin, destination, cargo, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (name, vessel_type, direction, origin, destination, cargo, notes),
        )

    def ships(
        self,
        *,
        vessel_type: str = None,
        direction:   str = None,
        limit:       int = 100,
    ) -> list[dict]:
        clauses, params = [], []
        if vessel_type:
            clauses.append("vessel_type = ?"); params.append(vessel_type)
        if direction:
            clauses.append("direction = ?");   params.append(direction)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return self._rows(
            f"SELECT * FROM ships {where} ORDER BY id DESC LIMIT ?",
            (*params, limit),
        )

    def ship_count(self, vessel_type: str = None) -> int:
        if vessel_type:
            row = self._rows(
                "SELECT COUNT(*) AS n FROM ships WHERE vessel_type = ?", (vessel_type,))
        else:
            row = self._rows("SELECT COUNT(*) AS n FROM ships")
        return row[0]['n'] if row else 0

    # ── Art assets ────────────────────────────────────────────────────────────

    def register_asset(
        self,
        filename:    str,
        *,
        category:    str = None,
        description: str = None,
        tags:        str = None,
        campaign_id: str = None,
        width:       int = None,
        height:      int = None,
    ) -> int:
        """
        Register an image file in the inventory.
        If the filename already exists the record is updated in place.
        """
        existing = self._rows(
            "SELECT id FROM art_assets WHERE filename = ?", (filename,))
        if existing:
            self._run(
                """UPDATE art_assets
                   SET category=?, description=?, tags=?, campaign_id=?, width=?, height=?
                   WHERE filename=?""",
                (category, description, tags, campaign_id, width, height, filename),
            )
            return existing[0]['id']
        return self._run(
            """INSERT INTO art_assets (filename, category, description, tags, campaign_id, width, height)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (filename, category, description, tags, campaign_id, width, height),
        )

    def art_assets(
        self,
        *,
        category:    str = None,
        campaign_id: str = None,
        tag:         str = None,
    ) -> list[dict]:
        clauses, params = [], []
        if category:
            clauses.append("category = ?");    params.append(category)
        if campaign_id:
            clauses.append("campaign_id = ?"); params.append(campaign_id)
        if tag:
            clauses.append("tags LIKE ?");     params.append(f'%{tag}%')
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return self._rows(
            f"SELECT * FROM art_assets {where} ORDER BY category, filename",
            tuple(params),
        )

    def remove_asset(self, filename: str):
        self._run("DELETE FROM art_assets WHERE filename = ?", (filename,))

    # ── Lock radio ────────────────────────────────────────────────────────────

    def new_radio_thread(self) -> int:
        """Return a fresh thread_id (one higher than the current max, or 1)."""
        row = self._rows("SELECT MAX(thread_id) AS m FROM lock_radio")
        m = row[0]['m'] if row else None
        return (m or 0) + 1

    def add_lock_radio_message(
        self,
        sender_type: str,
        sender_name: str,
        message:     str,
        *,
        thread_id:   int = None,
        vessel_name: str = None,
        direction:   str = None,
    ) -> int:
        """
        Log one transmission.

        If *thread_id* is None a new thread is started automatically.
        Returns the row id of the inserted message.
        """
        if thread_id is None:
            thread_id = self.new_radio_thread()
        return self._run(
            """INSERT INTO lock_radio
               (thread_id, sender_type, sender_name, vessel_name, direction, message)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (thread_id, sender_type, sender_name, vessel_name, direction, message),
        )

    def lock_radio_messages(
        self,
        *,
        sender_type: str = None,
        thread_id:   int = None,
        vessel_name: str = None,
        limit:       int = 100,
    ) -> list[dict]:
        clauses, params = [], []
        if sender_type:
            clauses.append("sender_type = ?"); params.append(sender_type)
        if thread_id is not None:
            clauses.append("thread_id = ?");   params.append(thread_id)
        if vessel_name:
            clauses.append("vessel_name = ?"); params.append(vessel_name)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return self._rows(
            f"SELECT * FROM lock_radio {where} ORDER BY id ASC LIMIT ?",
            (*params, limit),
        )

    # ── Counts / summary ──────────────────────────────────────────────────────

    def summary(self) -> dict:
        """Return row counts for each table — useful for debugging."""
        return {
            'crew':          self._rows("SELECT COUNT(*) AS n FROM crew")[0]['n'],
            'crew_messages': self._rows("SELECT COUNT(*) AS n FROM crew_messages")[0]['n'],
            'ships':         self._rows("SELECT COUNT(*) AS n FROM ships")[0]['n'],
            'art_assets':    self._rows("SELECT COUNT(*) AS n FROM art_assets")[0]['n'],
            'lock_radio':    self._rows("SELECT COUNT(*) AS n FROM lock_radio")[0]['n'],
        }