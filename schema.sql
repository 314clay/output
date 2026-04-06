CREATE TABLE channels (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  metadata JSONB NOT NULL DEFAULT '{}',
  archived_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE items (
  id SERIAL PRIMARY KEY,
  channel_id TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
  format TEXT NOT NULL CHECK (format IN (
    'text', 'image', 'html', 'chart', 'table', 'log', 'json', 'diff',
    'math', 'media', 'progress', 'list'
  )),
  title TEXT,
  content JSONB NOT NULL,
  pinned BOOLEAN NOT NULL DEFAULT FALSE,
  slot_name TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE file_uploads (
  id SERIAL PRIMARY KEY,
  item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  file_path TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  size_bytes INTEGER,
  original_name TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_items_slot ON items(channel_id, slot_name) WHERE slot_name IS NOT NULL;
CREATE INDEX idx_items_channel ON items(channel_id, created_at DESC);
CREATE INDEX idx_channels_active ON channels(archived_at) WHERE archived_at IS NULL;
CREATE INDEX idx_items_pinned ON items(channel_id, pinned) WHERE pinned = TRUE;
CREATE INDEX idx_file_uploads_item ON file_uploads(item_id);
