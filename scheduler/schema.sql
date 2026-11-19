PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS groups (
    id         INTEGER PRIMARY KEY,
    slug       TEXT    NOT NULL UNIQUE,          -- the unguessable part of the share link
    name       TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS members (
    id       INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    name     TEXT    NOT NULL COLLATE NOCASE,    -- "Dana" and "dana" are the same person
    key_hash TEXT    NOT NULL,                   -- sha256 of the member's edit key
    UNIQUE (group_id, name)
);

-- One row per free half-hour. The primary key makes "is member m free in slot s" an index
-- lookup and rules out duplicates; WITHOUT ROWID stores the rows inside that index.
CREATE TABLE IF NOT EXISTS availability (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    slot      INTEGER NOT NULL CHECK (slot BETWEEN 0 AND 195),
    PRIMARY KEY (member_id, slot)
) WITHOUT ROWID;
