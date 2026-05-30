CREATE TABLE IF NOT EXISTS entries (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL,
    traits      TEXT NOT NULL,   -- comma-separated
    level       INTEGER,
    source_book TEXT,
    text        TEXT NOT NULL,
    stats_json  TEXT NOT NULL DEFAULT '[]',  -- JSON array of [label, value] pairs
    raw_json    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entries_category ON entries(category);
-- COLLATE NOCASE so case-insensitive get_by_name lookups use the index
-- instead of a full table scan.
CREATE INDEX IF NOT EXISTS idx_entries_name ON entries(name COLLATE NOCASE);

-- External-content FTS5 table over the searchable fields.
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    name,
    category UNINDEXED,
    traits,
    text,
    content='entries',
    content_rowid='rowid'
);
