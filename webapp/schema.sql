DROP TABLE IF EXISTS tags;
DROP TABLE IF EXISTS pictures;

CREATE TABLE pictures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT,                       -- NULL until an image is uploaded (seeded entries start empty)
    original_filename TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    picture_id INTEGER NOT NULL REFERENCES pictures(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL
);

CREATE INDEX idx_tags_keyword    ON tags(keyword);
CREATE INDEX idx_tags_picture_id ON tags(picture_id);
