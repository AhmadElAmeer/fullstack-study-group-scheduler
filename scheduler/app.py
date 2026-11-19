"""Flask app: a JSON API under /api plus two static pages.

There are no accounts. A group is reached through its share link (an unguessable slug).
Joining a group returns a member key; only a request carrying that key can change that
member's availability or remove them. The key is stored hashed, so the database alone
can't be used to edit anyone.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3

from flask import Flask, abort, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from . import db, grid
from .planner import find_windows

NAME_MAX = 40
MAX_MEMBERS = 60            # a study group, not a lecture hall; keeps the heatmap readable
DURATIONS = range(grid.SLOT_MIN, 8 * 60 + 1, grid.SLOT_MIN)   # 30 min .. 8 h


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def create_app(database: str | None = None) -> Flask:
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config["DATABASE"] = database or os.environ.get("SCHEDULER_DB", "scheduler.db")
    app.json.sort_keys = False
    db.init_db(app.config["DATABASE"])
    app.teardown_appcontext(db.close_db)

    @app.errorhandler(ApiError)
    def api_error(e: ApiError):
        return jsonify(error=e.message), e.status

    @app.errorhandler(HTTPException)
    def http_error(e: HTTPException):
        if request.path.startswith("/api/"):
            return jsonify(error=e.description), e.code
        return e

    # ---- pages ----

    @app.get("/")
    def home():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/g/<slug>")
    def group_page(slug: str):
        _group(slug, api=False)
        return send_from_directory(app.static_folder, "group.html")

    # ---- API ----

    @app.post("/api/groups")
    def create_group():
        name = _name(_body().get("name"), "group name")
        slug = secrets.token_urlsafe(9)  # 72 random bits
        db.get_db().execute("INSERT INTO groups (slug, name) VALUES (?, ?)", (slug, name))
        db.get_db().commit()
        return jsonify(slug=slug, name=name, url=f"/g/{slug}"), 201

    @app.get("/api/groups/<slug>")
    def get_group(slug: str):
        group = _group(slug)
        members = _members_with_slots(group["id"])
        heat = [0] * grid.SLOT_COUNT
        for m in members:
            for s in m["slots"]:
                heat[s] += 1
        return jsonify(slug=group["slug"], name=group["name"], grid=grid.describe(),
                       members=members, heat=heat)

    @app.post("/api/groups/<slug>/members")
    def join(slug: str):
        group = _group(slug)
        name = _name(_body().get("name"), "your name")
        conn = db.get_db()
        count = conn.execute("SELECT COUNT(*) FROM members WHERE group_id = ?", (group["id"],)).fetchone()[0]
        if count >= MAX_MEMBERS:
            raise ApiError(409, f"this group is full ({MAX_MEMBERS} members)")
        key = secrets.token_urlsafe(24)
        try:
            cur = conn.execute("INSERT INTO members (group_id, name, key_hash) VALUES (?, ?, ?)",
                               (group["id"], name, _hash(key)))
        except sqlite3.IntegrityError:
            raise ApiError(409, f"someone called '{name}' is already in this group")
        conn.commit()
        return jsonify(id=cur.lastrowid, name=name, key=key), 201

    @app.put("/api/groups/<slug>/members/<int:member_id>/availability")
    def set_availability(slug: str, member_id: int):
        group = _group(slug)
        _authorize(group["id"], member_id)
        slots = _body().get("slots")
        if not isinstance(slots, list) or not all(type(s) is int for s in slots):
            raise ApiError(400, "'slots' must be a list of slot numbers")
        bad = [s for s in slots if not 0 <= s < grid.SLOT_COUNT]
        if bad:
            raise ApiError(400, f"slot {bad[0]} is outside the week (0-{grid.SLOT_COUNT - 1})")
        unique = sorted(set(slots))
        conn = db.get_db()
        with conn:  # one transaction: readers never see a half-replaced week
            conn.execute("DELETE FROM availability WHERE member_id = ?", (member_id,))
            conn.executemany("INSERT INTO availability (member_id, slot) VALUES (?, ?)",
                             [(member_id, s) for s in unique])
        return jsonify(id=member_id, slots=unique)

    @app.delete("/api/groups/<slug>/members/<int:member_id>")
    def leave(slug: str, member_id: int):
        group = _group(slug)
        _authorize(group["id"], member_id)
        conn = db.get_db()
        with conn:
            conn.execute("DELETE FROM members WHERE id = ?", (member_id,))  # availability cascades
        return "", 204

    @app.get("/api/groups/<slug>/suggestions")
    def suggestions(slug: str):
        group = _group(slug)
        members = _members_with_slots(group["id"])
        names = {m["id"]: m["name"] for m in members}
        duration_min = _int_arg("duration", 60)
        if duration_min not in DURATIONS:
            raise ApiError(400, "duration must be a multiple of 30 minutes, from 30 to 480")
        quorum = _int_arg("quorum", max(len(members), 1))
        if quorum < 1:
            raise ApiError(400, "quorum must be at least 1")
        required = []
        for raw in request.args.getlist("required"):
            if not raw.isdigit() or int(raw) not in names:
                raise ApiError(400, f"required member {raw!r} is not in this group")
            required.append(int(raw))
        limit = min(_int_arg("limit", 10), 50)

        windows = []
        if members:
            found = find_windows({m["id"]: m["slots"] for m in members},
                                 duration=duration_min // grid.SLOT_MIN, quorum=quorum,
                                 required=required, limit=limit)
            for w in found:
                day = grid.day_of(w.start)
                first = w.start - day * grid.SLOTS_PER_DAY
                windows.append({
                    "day": grid.DAYS[day],
                    "start": grid.clock(first),
                    "end": grid.clock(first + w.length),
                    "minutes": w.length * grid.SLOT_MIN,
                    "start_slot": w.start,
                    "end_slot": w.end,
                    "attendees": sorted((names[i] for i in w.members), key=str.lower),
                    "missing": sorted((n for i, n in names.items() if i not in w.members), key=str.lower),
                })
        return jsonify(total_members=len(members), duration=duration_min, quorum=quorum,
                       windows=windows)

    return app


# ---- helpers ----

def _body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "expected a JSON object")
    return data


def _name(value, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApiError(400, f"{what} is required")
    name = " ".join(value.split())  # trim and collapse inner whitespace
    if len(name) > NAME_MAX:
        raise ApiError(400, f"{what} can be at most {NAME_MAX} characters")
    return name


def _int_arg(key: str, default: int) -> int:
    raw = request.args.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ApiError(400, f"'{key}' must be a whole number")


def _group(slug: str, api: bool = True) -> sqlite3.Row:
    row = db.get_db().execute("SELECT id, slug, name FROM groups WHERE slug = ?", (slug,)).fetchone()
    if row is None:
        if api:
            raise ApiError(404, "no group with this link")
        abort(404)
    return row


def _members_with_slots(group_id: int) -> list[dict]:
    rows = db.get_db().execute(
        """SELECT m.id, m.name, a.slot
           FROM members m LEFT JOIN availability a ON a.member_id = m.id
           WHERE m.group_id = ?
           ORDER BY m.id, a.slot""", (group_id,)).fetchall()
    members: dict[int, dict] = {}
    for r in rows:
        m = members.setdefault(r["id"], {"id": r["id"], "name": r["name"], "slots": []})
        if r["slot"] is not None:
            m["slots"].append(r["slot"])
    return list(members.values())


def _authorize(group_id: int, member_id: int) -> None:
    row = db.get_db().execute("SELECT key_hash FROM members WHERE id = ? AND group_id = ?",
                              (member_id, group_id)).fetchone()
    if row is None:
        raise ApiError(404, "no such member in this group")
    key = request.headers.get("X-Member-Key", "")
    if not hmac.compare_digest(_hash(key), row["key_hash"]):
        raise ApiError(403, "this member key doesn't match; only the member can change their times")


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()
