"""
Accès à la base de données — SQLite pur via le module 'sqlite3' de Python
(déjà installé avec Python, aucune installation supplémentaire nécessaire).

Choix volontaire : pas de SQLAlchemy. Sur certains PC Windows, l'installation
de bibliothèques comme SQLAlchemy/psycopg2 peut échouer si les outils de
compilation ne sont pas installés. Le module sqlite3 est fourni nativement
avec Python, donc ce problème ne peut plus se produire.
"""
import os
import sqlite3
import uuid
import json
from datetime import datetime, date
from flask import g
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "arppsd.db"))


def gen_id():
    return uuid.uuid4().hex[:12]


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


class Row(dict):
    """Petit adaptateur pour pouvoir écrire m.first_name au lieu de m['first_name']
    dans les templates, comme avec un ORM classique."""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            return None

    def __setattr__(self, key, value):
        self[key] = value


def _parse_date(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_datetime(value):
    if not value:
        return None
    return datetime.fromisoformat(value)


def row_to_member(r):
    if r is None:
        return None
    d = Row(dict(r))
    d.join_date = _parse_date(d.get("join_date"))
    d.full_name = f"{d.get('first_name','')} {d.get('last_name','')}"
    return d


def row_to_contribution(r):
    if r is None:
        return None
    d = Row(dict(r))
    d.date_paid = _parse_date(d.get("date_paid"))
    return d


def row_to_caisse(r):
    if r is None:
        return None
    d = Row(dict(r))
    d.date = _parse_date(d.get("date"))
    return d


def row_to_activity(r):
    if r is None:
        return None
    d = Row(dict(r))
    d.date = _parse_date(d.get("date"))
    return d


def row_to_announcement(r):
    if r is None:
        return None
    d = Row(dict(r))
    d.date = _parse_datetime(d.get("date"))
    return d


def row_to_document(r):
    if r is None:
        return None
    d = Row(dict(r))
    d.date_added = _parse_datetime(d.get("date_added"))
    return d


def row_to_log(r):
    if r is None:
        return None
    d = Row(dict(r))
    d.timestamp = _parse_datetime(d.get("timestamp"))
    return d


# ============================== SCHÉMA ==============================

SCHEMA = """
CREATE TABLE IF NOT EXISTS member (
    id TEXT PRIMARY KEY,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    phone TEXT, address TEXT, fonction TEXT DEFAULT 'MEMBRE',
    member_code TEXT, join_date TEXT, status TEXT DEFAULT 'actif',
    notes TEXT, is_demo INTEGER DEFAULT 0, password_hash TEXT
);

CREATE TABLE IF NOT EXISTS contribution (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL REFERENCES member(id) ON DELETE CASCADE,
    month INTEGER NOT NULL, year INTEGER NOT NULL, amount INTEGER NOT NULL,
    date_paid TEXT, recorded_by TEXT, is_demo INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS caisse_operation (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL, amount INTEGER NOT NULL, date TEXT,
    motif TEXT, responsable TEXT, is_demo INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS activity (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL, description TEXT, date TEXT, time TEXT,
    location TEXT, responsable TEXT, status TEXT DEFAULT 'prévue',
    report TEXT, is_demo INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS activity_participant (
    activity_id TEXT NOT NULL REFERENCES activity(id) ON DELETE CASCADE,
    member_id TEXT NOT NULL REFERENCES member(id) ON DELETE CASCADE,
    PRIMARY KEY (activity_id, member_id)
);

CREATE TABLE IF NOT EXISTS announcement (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL, content TEXT, date TEXT, author TEXT,
    status TEXT DEFAULT 'publié', is_demo INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS document (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL, category TEXT, note TEXT, date_added TEXT,
    added_by TEXT, is_demo INTEGER DEFAULT 0,
    filename TEXT, original_name TEXT, file_size INTEGER
);

CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    action TEXT, user TEXT, timestamp TEXT, details TEXT
);

CREATE TABLE IF NOT EXISTS setting (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS notification (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL, message TEXT, link TEXT,
    target_role TEXT, target_member_id TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS notification_read (
    notification_id TEXT NOT NULL REFERENCES notification(id) ON DELETE CASCADE,
    member_id TEXT NOT NULL,
    PRIMARY KEY (notification_id, member_id)
);
"""


def _ensure_columns(db, table, columns):
    """Ajoute les colonnes manquantes à une table existante (mise à jour sans
    devoir supprimer la base de données à chaque évolution du schéma)."""
    existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
    for col_name, col_def in columns:
        if col_name not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")


def init_db(app):
    import gdrive
    gdrive.restore_db_file_if_missing(DB_PATH)
    with app.app_context():
        db = get_db()
        db.executescript(SCHEMA)
        _ensure_columns(db, "member", [("password_hash", "password_hash TEXT")])
        _ensure_columns(db, "document", [
            ("filename", "filename TEXT"),
            ("original_name", "original_name TEXT"),
            ("file_size", "file_size INTEGER"),
            ("drive_file_id", "drive_file_id TEXT"),
        ])
        db.commit()
        close_db()
    app.teardown_appcontext(close_db)


# ============================== PARAMÈTRES ==============================

def get_setting(key, default=None):
    db = get_db()
    row = db.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except (TypeError, ValueError):
        return row["value"]


def set_setting(key, value):
    db = get_db()
    payload = value if isinstance(value, str) else json.dumps(value)
    db.execute(
        "INSERT INTO setting (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, payload),
    )
    db.commit()


# ============================== MEMBRES ==============================

def get_members(status=None):
    db = get_db()
    if status and status != "tous":
        rows = db.execute("SELECT * FROM member WHERE status = ? ORDER BY first_name", (status,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM member ORDER BY first_name").fetchall()
    return [row_to_member(r) for r in rows]


def get_member(member_id):
    db = get_db()
    return row_to_member(db.execute("SELECT * FROM member WHERE id = ?", (member_id,)).fetchone())


def count_members():
    return get_db().execute("SELECT COUNT(*) c FROM member").fetchone()["c"]


def insert_member(data):
    db = get_db()
    mid = gen_id()
    db.execute(
        "INSERT INTO member (id, first_name, last_name, phone, address, fonction, member_code, "
        "join_date, status, notes, is_demo) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (mid, data["first_name"], data["last_name"], data.get("phone"), data.get("address"),
         data.get("fonction", "MEMBRE"), data.get("member_code"), data["join_date"],
         data.get("status", "actif"), data.get("notes"), int(data.get("is_demo", False))),
    )
    db.commit()
    return mid


def update_member(member_id, data):
    db = get_db()
    db.execute(
        "UPDATE member SET first_name=?, last_name=?, phone=?, address=?, fonction=?, "
        "member_code=?, join_date=?, notes=? WHERE id=?",
        (data["first_name"], data["last_name"], data.get("phone"), data.get("address"),
         data.get("fonction", "MEMBRE"), data.get("member_code"), data["join_date"],
         data.get("notes"), member_id),
    )
    db.commit()


def toggle_member_status(member_id):
    db = get_db()
    m = get_member(member_id)
    new_status = "inactif" if m.status == "actif" else "actif"
    db.execute("UPDATE member SET status=? WHERE id=?", (new_status, member_id))
    db.commit()
    return new_status


def set_member_password(member_id, password):
    """Enregistre un mot de passe de façon chiffrée (jamais en clair dans la base)."""
    db = get_db()
    db.execute("UPDATE member SET password_hash=? WHERE id=?",
               (generate_password_hash(password), member_id))
    db.commit()


def verify_member_password(member_id, password):
    db = get_db()
    row = db.execute("SELECT password_hash FROM member WHERE id=?", (member_id,)).fetchone()
    if not row or not row["password_hash"]:
        return False
    return check_password_hash(row["password_hash"], password)


def member_has_password(member_id):
    db = get_db()
    row = db.execute("SELECT password_hash FROM member WHERE id=?", (member_id,)).fetchone()
    return bool(row and row["password_hash"])


# ============================== COTISATIONS ==============================

def get_contributions_for_member(member_id, year=None):
    db = get_db()
    if year:
        rows = db.execute(
            "SELECT * FROM contribution WHERE member_id=? AND year=? ORDER BY month DESC",
            (member_id, year),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM contribution WHERE member_id=? ORDER BY year DESC, month DESC",
            (member_id,),
        ).fetchall()
    return [row_to_contribution(r) for r in rows]


def count_contributions_for_member(member_id, year):
    db = get_db()
    return db.execute(
        "SELECT COUNT(*) c FROM contribution WHERE member_id=? AND year=?", (member_id, year)
    ).fetchone()["c"]


def sum_contributions(year=None, month=None):
    db = get_db()
    q = "SELECT COALESCE(SUM(amount),0) s FROM contribution WHERE 1=1"
    params = []
    if year:
        q += " AND year=?"
        params.append(year)
    if month:
        q += " AND month=?"
        params.append(month)
    return db.execute(q, params).fetchone()["s"]


def get_contribution(contrib_id):
    db = get_db()
    return row_to_contribution(db.execute("SELECT * FROM contribution WHERE id=?", (contrib_id,)).fetchone())


def find_contribution(member_id, month, year):
    db = get_db()
    return row_to_contribution(
        db.execute("SELECT * FROM contribution WHERE member_id=? AND month=? AND year=?",
                   (member_id, month, year)).fetchone()
    )


def upsert_contribution(member_id, month, year, amount, date_paid, recorded_by):
    db = get_db()
    existing = find_contribution(member_id, month, year)
    if existing:
        db.execute("UPDATE contribution SET amount=?, date_paid=?, recorded_by=? WHERE id=?",
                   (amount, date_paid, recorded_by, existing.id))
    else:
        db.execute(
            "INSERT INTO contribution (id, member_id, month, year, amount, date_paid, recorded_by, is_demo) "
            "VALUES (?,?,?,?,?,?,?,0)",
            (gen_id(), member_id, month, year, amount, date_paid, recorded_by),
        )
    db.commit()


def delete_contribution(contrib_id):
    db = get_db()
    db.execute("DELETE FROM contribution WHERE id=?", (contrib_id,))
    db.commit()


# ============================== CAISSE SOCIALE ==============================

def get_caisse_ops(type_filter=None):
    db = get_db()
    if type_filter and type_filter != "tous":
        rows = db.execute("SELECT * FROM caisse_operation WHERE type=? ORDER BY date DESC", (type_filter,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM caisse_operation ORDER BY date DESC").fetchall()
    return [row_to_caisse(r) for r in rows]


def caisse_totals():
    db = get_db()
    total_in = db.execute("SELECT COALESCE(SUM(amount),0) s FROM caisse_operation WHERE type='entrée'").fetchone()["s"]
    total_out = db.execute("SELECT COALESCE(SUM(amount),0) s FROM caisse_operation WHERE type='sortie'").fetchone()["s"]
    return total_in, total_out, total_in - total_out


def insert_caisse_op(type_, amount, date_, motif, responsable):
    db = get_db()
    db.execute(
        "INSERT INTO caisse_operation (id, type, amount, date, motif, responsable, is_demo) VALUES (?,?,?,?,?,?,0)",
        (gen_id(), type_, amount, date_, motif, responsable),
    )
    db.commit()


# ============================== ACTIVITÉS ==============================

def _attach_participants(activity):
    db = get_db()
    rows = db.execute(
        "SELECT m.* FROM member m JOIN activity_participant ap ON ap.member_id = m.id "
        "WHERE ap.activity_id = ? ORDER BY m.first_name", (activity.id,)
    ).fetchall()
    activity.participants = [row_to_member(r) for r in rows]
    return activity


def get_activities(status_filter=None):
    db = get_db()
    if status_filter and status_filter != "tous":
        rows = db.execute("SELECT * FROM activity WHERE status=? ORDER BY date DESC", (status_filter,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM activity ORDER BY date DESC").fetchall()
    acts = [row_to_activity(r) for r in rows]
    for a in acts:
        _attach_participants(a)
    return acts


def get_activity(activity_id):
    db = get_db()
    a = row_to_activity(db.execute("SELECT * FROM activity WHERE id=?", (activity_id,)).fetchone())
    if a:
        _attach_participants(a)
    return a


def count_activities(status=None):
    db = get_db()
    if status:
        return db.execute("SELECT COUNT(*) c FROM activity WHERE status=?", (status,)).fetchone()["c"]
    return db.execute("SELECT COUNT(*) c FROM activity").fetchone()["c"]


def insert_activity(data, participant_ids):
    db = get_db()
    aid = gen_id()
    db.execute(
        "INSERT INTO activity (id, title, description, date, time, location, responsable, status, report, is_demo) "
        "VALUES (?,?,?,?,?,?,?,?,?,0)",
        (aid, data["title"], data.get("description"), data["date"], data.get("time"),
         data.get("location"), data.get("responsable"), data.get("status", "prévue"), data.get("report")),
    )
    for mid in participant_ids:
        db.execute("INSERT OR IGNORE INTO activity_participant (activity_id, member_id) VALUES (?,?)", (aid, mid))
    db.commit()
    return aid


def update_activity(activity_id, data, participant_ids):
    db = get_db()
    db.execute(
        "UPDATE activity SET title=?, description=?, date=?, time=?, location=?, responsable=?, "
        "status=?, report=? WHERE id=?",
        (data["title"], data.get("description"), data["date"], data.get("time"), data.get("location"),
         data.get("responsable"), data.get("status", "prévue"), data.get("report"), activity_id),
    )
    db.execute("DELETE FROM activity_participant WHERE activity_id=?", (activity_id,))
    for mid in participant_ids:
        db.execute("INSERT OR IGNORE INTO activity_participant (activity_id, member_id) VALUES (?,?)",
                   (activity_id, mid))
    db.commit()


def get_upcoming_activities(limit=3):
    db = get_db()
    rows = db.execute(
        "SELECT * FROM activity WHERE status IN ('prévue','en cours') ORDER BY date ASC LIMIT ?", (limit,)
    ).fetchall()
    return [row_to_activity(r) for r in rows]


# ============================== ANNONCES ==============================

def get_announcements():
    db = get_db()
    rows = db.execute("SELECT * FROM announcement ORDER BY date DESC").fetchall()
    return [row_to_announcement(r) for r in rows]


def get_recent_published_announcements(limit=3):
    db = get_db()
    rows = db.execute(
        "SELECT * FROM announcement WHERE status='publié' ORDER BY date DESC LIMIT ?", (limit,)
    ).fetchall()
    return [row_to_announcement(r) for r in rows]


def insert_announcement(title, content, status, author):
    db = get_db()
    db.execute(
        "INSERT INTO announcement (id, title, content, date, author, status, is_demo) VALUES (?,?,?,?,?,?,0)",
        (gen_id(), title, content, datetime.utcnow().isoformat(), author, status),
    )
    db.commit()


def update_announcement(ann_id, title, content, status):
    db = get_db()
    db.execute("UPDATE announcement SET title=?, content=?, status=? WHERE id=?", (title, content, status, ann_id))
    db.commit()


def get_announcement(ann_id):
    db = get_db()
    return row_to_announcement(db.execute("SELECT * FROM announcement WHERE id=?", (ann_id,)).fetchone())


# ============================== DOCUMENTS ==============================

def get_documents(category=None):
    db = get_db()
    if category and category != "Toutes":
        rows = db.execute("SELECT * FROM document WHERE category=? ORDER BY date_added DESC", (category,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM document ORDER BY date_added DESC").fetchall()
    return [row_to_document(r) for r in rows]


def get_recent_documents(limit=3):
    db = get_db()
    rows = db.execute("SELECT * FROM document ORDER BY date_added DESC LIMIT ?", (limit,)).fetchall()
    return [row_to_document(r) for r in rows]


def insert_document(name, category, note, added_by, filename=None, original_name=None,
                     file_size=None, drive_file_id=None):
    db = get_db()
    db.execute(
        "INSERT INTO document (id, name, category, note, date_added, added_by, is_demo, "
        "filename, original_name, file_size, drive_file_id) VALUES (?,?,?,?,?,?,0,?,?,?,?)",
        (gen_id(), name, category, note, datetime.utcnow().isoformat(), added_by,
         filename, original_name, file_size, drive_file_id),
    )
    db.commit()


def get_document(doc_id):
    db = get_db()
    return row_to_document(db.execute("SELECT * FROM document WHERE id=?", (doc_id,)).fetchone())


def delete_document(doc_id):
    db = get_db()
    row = db.execute("SELECT name, filename, drive_file_id FROM document WHERE id=?", (doc_id,)).fetchone()
    name = row["name"] if row else ""
    stored_filename = row["filename"] if row else None
    drive_file_id = row["drive_file_id"] if row else None
    db.execute("DELETE FROM document WHERE id=?", (doc_id,))
    db.commit()
    return name, stored_filename, drive_file_id


def search_documents(q, limit=10):
    db = get_db()
    like = f"%{q}%"
    rows = db.execute(
        "SELECT * FROM document WHERE name LIKE ? OR note LIKE ? OR category LIKE ? "
        "ORDER BY date_added DESC LIMIT ?", (like, like, like, limit)
    ).fetchall()
    return [row_to_document(r) for r in rows]


# ============================== RECHERCHE GLOBALE ==============================

def search_members(q, limit=10):
    db = get_db()
    like = f"%{q}%"
    rows = db.execute(
        "SELECT * FROM member WHERE first_name LIKE ? OR last_name LIKE ? OR member_code LIKE ? "
        "OR phone LIKE ? ORDER BY first_name LIMIT ?", (like, like, like, like, limit)
    ).fetchall()
    return [row_to_member(r) for r in rows]


def search_activities(q, limit=10):
    db = get_db()
    like = f"%{q}%"
    rows = db.execute(
        "SELECT * FROM activity WHERE title LIKE ? OR description LIKE ? OR location LIKE ? "
        "ORDER BY date DESC LIMIT ?", (like, like, like, limit)
    ).fetchall()
    return [row_to_activity(r) for r in rows]


def search_announcements(q, limit=10):
    db = get_db()
    like = f"%{q}%"
    rows = db.execute(
        "SELECT * FROM announcement WHERE title LIKE ? OR content LIKE ? ORDER BY date DESC LIMIT ?",
        (like, like, limit)
    ).fetchall()
    return [row_to_announcement(r) for r in rows]


# ============================== NOTIFICATIONS ==============================

def insert_notification(title, message, link=None, target_role=None, target_member_id=None):
    db = get_db()
    nid = gen_id()
    db.execute(
        "INSERT INTO notification (id, title, message, link, target_role, target_member_id, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (nid, title, message, link, target_role, target_member_id, datetime.utcnow().isoformat()),
    )
    db.commit()
    return nid


def get_notifications_for_user(member_id, role, limit=20):
    db = get_db()
    rows = db.execute(
        "SELECT n.*, (r.member_id IS NOT NULL) AS is_read FROM notification n "
        "LEFT JOIN notification_read r ON r.notification_id = n.id AND r.member_id = ? "
        "WHERE n.target_member_id = ? OR n.target_member_id IS NULL AND (n.target_role = ? OR n.target_role IS NULL) "
        "ORDER BY n.created_at DESC LIMIT ?",
        (member_id, member_id, role, limit),
    ).fetchall()
    result = []
    for r in rows:
        d = Row(dict(r))
        d.created_at = _parse_datetime(d.get("created_at"))
        d.is_read = bool(d.is_read)
        result.append(d)
    return result


def count_unread_notifications(member_id, role):
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) c FROM notification n "
        "LEFT JOIN notification_read r ON r.notification_id = n.id AND r.member_id = ? "
        "WHERE (n.target_member_id = ? OR n.target_member_id IS NULL AND (n.target_role = ? OR n.target_role IS NULL)) "
        "AND r.member_id IS NULL",
        (member_id, member_id, role),
    ).fetchone()
    return row["c"]


def mark_notification_read(notification_id, member_id):
    db = get_db()
    db.execute(
        "INSERT OR IGNORE INTO notification_read (notification_id, member_id) VALUES (?,?)",
        (notification_id, member_id),
    )
    db.commit()


def mark_all_notifications_read(member_id, role):
    db = get_db()
    notifs = get_notifications_for_user(member_id, role, limit=500)
    for n in notifs:
        db.execute(
            "INSERT OR IGNORE INTO notification_read (notification_id, member_id) VALUES (?,?)",
            (n.id, member_id),
        )
    db.commit()


# ============================== JOURNAL D'ACTIVITÉ ==============================

def add_audit_log(action, user, details=""):
    db = get_db()
    db.execute(
        "INSERT INTO audit_log (id, action, user, timestamp, details) VALUES (?,?,?,?,?)",
        (gen_id(), action, user, datetime.utcnow().isoformat(), details),
    )
    db.commit()


def get_audit_logs(limit=50):
    db = get_db()
    rows = db.execute("SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
    return [row_to_log(r) for r in rows]


# ============================== RÉINITIALISATION ==============================

def clear_all_data():
    db = get_db()
    for table in ["activity_participant", "contribution", "caisse_operation", "activity",
                  "announcement", "document", "notification_read", "notification", "member"]:
        db.execute(f"DELETE FROM {table}")
    db.commit()
