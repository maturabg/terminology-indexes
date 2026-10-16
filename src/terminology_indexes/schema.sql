CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
-- schema_version, norm_version, built_at, release_tag

CREATE TABLE sources (
  source TEXT PRIMARY KEY, snapshot_version TEXT, fetched_at TEXT,
  raw_sha256 TEXT, row_count INTEGER, license TEXT, attribution TEXT
);

CREATE TABLE entries (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL, external_id TEXT NOT NULL,
  url TEXT NOT NULL, title TEXT NOT NULL,
  kind TEXT NOT NULL,           -- term | concept | document | spec_section
  lang TEXT,                    -- en | bg | mul
  status TEXT DEFAULT 'active', -- active | deprecated | redirect
  replaced_by TEXT,             -- external_id of the replacement (CWE, EuroVoc)
  snippet TEXT,                 -- only if snippet_policy allows it
  extra TEXT,                   -- JSON: domain, type, spec version
  UNIQUE (source, external_id)
);

CREATE TABLE labels (
  entry_id INTEGER REFERENCES entries(id),
  label TEXT, label_norm TEXT, label_key TEXT,
  lang TEXT, label_type TEXT    -- pref | alt | hidden | redirect
);
CREATE INDEX labels_key ON labels(label_key);
CREATE INDEX labels_entry ON labels(entry_id);
CREATE VIRTUAL TABLE labels_fts USING fts5(
  label_norm, content='labels', tokenize='unicode61 remove_diacritics 2'
);
