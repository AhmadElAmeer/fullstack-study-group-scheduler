import sqlite3

from scheduler.app import MAX_MEMBERS, NAME_MAX


# ---- groups ----

def test_create_group(client):
    r = client.post("/api/groups", json={"name": "  Data   Structures  "})
    assert r.status_code == 201
    assert r.json["name"] == "Data Structures"          # trimmed, inner spaces collapsed
    assert len(r.json["slug"]) == 12 and r.json["url"] == "/g/" + r.json["slug"]
    other = client.post("/api/groups", json={"name": "x"}).json["slug"]
    assert other != r.json["slug"]


def test_group_name_validation(client):
    for body, message in [({"name": ""}, "required"), ({"name": "   "}, "required"), ({}, "required"),
                          ({"name": 5}, "required"), ({"name": "x" * (NAME_MAX + 1)}, "at most 40")]:
        r = client.post("/api/groups", json=body)
        assert r.status_code == 400 and message in r.json["error"], (body, r.json)
    r = client.post("/api/groups", data="not json", content_type="text/plain")
    assert r.status_code == 400 and r.json["error"] == "expected a JSON object"
    assert client.post("/api/groups", json={"name": "x" * NAME_MAX}).status_code == 201


def test_get_group_has_grid_members_and_heat(api, client):
    slug = api.group("Algo")
    a, b = api.join(slug, "Dana"), api.join(slug, "Omar")
    api.put(slug, a, [0, 1, 2])
    api.put(slug, b, [2, 3])
    g = client.get(f"/api/groups/{slug}").json
    assert g["name"] == "Algo"
    assert g["grid"]["days"][0] == "Sun" and g["grid"]["slots_per_day"] == 28
    assert [(m["name"], m["slots"]) for m in g["members"]] == [("Dana", [0, 1, 2]), ("Omar", [2, 3])]
    assert g["heat"][:5] == [1, 1, 2, 1, 0] and len(g["heat"]) == 196
    assert "key" not in str(g)


def test_unknown_group_and_pages(client, api):
    assert client.get("/api/groups/nope").status_code == 404
    assert client.get("/api/groups/nope").json == {"error": "no group with this link"}
    assert client.post("/api/groups/nope/members", json={"name": "x"}).status_code == 404
    assert client.get("/g/nope").status_code == 404
    assert client.get("/").status_code == 200
    slug = api.group()
    page = client.get(f"/g/{slug}")
    assert page.status_code == 200 and b'id="grid"' in page.data
    # Unknown API routes and wrong methods answer in JSON too.
    assert client.get("/api/whatever").status_code == 404 and "error" in client.get("/api/whatever").json
    r = client.delete("/api/groups")
    assert r.status_code == 405 and "error" in r.json


# ---- members ----

def test_join_and_duplicate_names(api, client):
    slug = api.group()
    dana = api.join(slug, "Dana")
    assert dana["name"] == "Dana" and len(dana["key"]) >= 32
    r = client.post(f"/api/groups/{slug}/members", json={"name": "  dana "})
    assert r.status_code == 409 and "already in this group" in r.json["error"]
    # The same name is fine in another group.
    api.join(api.group("Other"), "Dana")


def test_group_size_limit(api, client):
    slug = api.group()
    for i in range(MAX_MEMBERS):
        api.join(slug, f"m{i}")
    r = client.post(f"/api/groups/{slug}/members", json={"name": "one more"})
    assert r.status_code == 409 and "full" in r.json["error"]


def test_keys_are_stored_hashed(api, app):
    slug = api.group()
    dana = api.join(slug, "Dana")
    conn = sqlite3.connect(app.config["DATABASE"])
    stored = conn.execute("SELECT key_hash FROM members").fetchone()[0]
    conn.close()
    assert dana["key"] not in stored and len(stored) == 64


def test_names_are_stored_literally(api, client):
    slug = api.group()
    tricky = "Robert'); DROP TABLE members;--"
    api.join(slug, tricky)
    api.join(slug, "<b>bold</b>")
    names = [m["name"] for m in client.get(f"/api/groups/{slug}").json["members"]]
    assert names == [tricky, "<b>bold</b>"]


# ---- availability ----

def test_set_availability_replaces_dedupes_and_sorts(api):
    slug = api.group()
    dana = api.join(slug, "Dana")
    r = api.put(slug, dana, [5, 3, 5, 4])
    assert r.status_code == 200 and r.json["slots"] == [3, 4, 5]
    assert api.put(slug, dana, [195]).json["slots"] == [195]
    assert api.put(slug, dana, []).json["slots"] == []
    # Read back from the database, not just the response: a new week replaces the old one.
    api.put(slug, dana, [1, 2, 3])
    api.put(slug, dana, [2, 9])
    assert api.c.get(f"/api/groups/{slug}").json["members"][0]["slots"] == [2, 9]


def test_availability_needs_the_members_own_key(api):
    slug = api.group()
    dana, omar = api.join(slug, "Dana"), api.join(slug, "Omar")
    for key in ["", "wrong", omar["key"]]:
        r = api.put(slug, dana, [1], key=key)
        assert r.status_code == 403 and "key" in r.json["error"]
    # A member of another group can't be reached through this group's link.
    other = api.group("Other")
    stranger = api.join(other, "Lina")
    assert api.put(slug, stranger, [1]).status_code == 404


def test_availability_validation(api):
    slug = api.group()
    dana = api.join(slug, "Dana")
    for slots, message in [("1,2", "list"), ([1, "2"], "list"), ([1.5], "list"), ([True], "list"),
                           ([196], "outside the week"), ([-1], "outside the week")]:
        r = api.put(slug, dana, slots)
        assert r.status_code == 400 and message in r.json["error"], (slots, r.json)
    # A rejected update leaves the old times untouched.
    api.put(slug, dana, [7])
    api.put(slug, dana, [7, 999])
    assert api.c.get(f"/api/groups/{slug}").json["members"][0]["slots"] == [7]


def test_leave_removes_member_and_their_times(api, app, client):
    slug = api.group()
    dana, omar = api.join(slug, "Dana"), api.join(slug, "Omar")
    api.put(slug, dana, [1, 2, 3])
    assert client.delete(f"/api/groups/{slug}/members/{dana['id']}", headers={"X-Member-Key": omar["key"]}).status_code == 403
    assert client.delete(f"/api/groups/{slug}/members/{dana['id']}", headers={"X-Member-Key": dana["key"]}).status_code == 204
    assert [m["name"] for m in client.get(f"/api/groups/{slug}").json["members"]] == ["Omar"]
    conn = sqlite3.connect(app.config["DATABASE"])
    assert conn.execute("SELECT COUNT(*) FROM availability").fetchone()[0] == 0  # cascaded
    conn.close()
    # The name is free again.
    api.join(slug, "Dana")


# ---- suggestions ----

def test_suggestions(api):
    slug = api.group()
    dana, omar, lina = api.join(slug, "Dana"), api.join(slug, "Omar"), api.join(slug, "lina")
    api.put(slug, dana, list(range(32, 40)))   # Mon 10:00-14:00
    api.put(slug, omar, list(range(34, 42)))   # Mon 11:00-15:00
    api.put(slug, lina, list(range(30, 38)))   # Mon 09:00-13:00

    r = api.suggest(slug, "?duration=90")
    assert r.status_code == 200
    assert r.json["quorum"] == 3                          # default: everyone
    assert r.json["windows"] == [{
        "day": "Mon", "start": "11:00", "end": "13:00", "minutes": 120,
        "start_slot": 34, "end_slot": 38,
        "attendees": ["Dana", "lina", "Omar"], "missing": []}]

    r = api.suggest(slug, f"?duration=150&quorum=2&required={omar['id']}")
    assert [(w["start"], w["end"], w["missing"]) for w in r.json["windows"]] == [("11:00", "14:00", ["lina"])]

    r = api.suggest(slug, "?duration=60&quorum=1&limit=2")
    assert len(r.json["windows"]) == 2


def test_suggestion_parameters_are_validated(api):
    slug = api.group()
    api.join(slug, "Dana")
    for query, message in [("?duration=45", "multiple of 30"), ("?duration=0", "multiple of 30"),
                           ("?duration=510", "multiple of 30"), ("?duration=abc", "whole number"),
                           ("?quorum=0", "at least 1"), ("?required=999", "not in this group"),
                           ("?required=x", "not in this group")]:
        r = api.suggest(slug, query)
        assert r.status_code == 400 and message in r.json["error"], (query, r.json)
    other = api.join(api.group("Other"), "Lina")
    assert api.suggest(slug, f"?required={other['id']}").status_code == 400


def test_suggestions_for_empty_group(api):
    slug = api.group()
    r = api.suggest(slug)
    assert r.json == {"total_members": 0, "duration": 60, "quorum": 1, "windows": []}
