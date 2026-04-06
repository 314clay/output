ALTER TABLE items ADD COLUMN slot_name TEXT;
CREATE UNIQUE INDEX idx_items_slot
  ON items(channel_id, slot_name) WHERE slot_name IS NOT NULL;
