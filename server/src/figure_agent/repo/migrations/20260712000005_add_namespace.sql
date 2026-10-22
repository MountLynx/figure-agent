ALTER TABLE item_types ADD COLUMN namespace TEXT NOT NULL DEFAULT 'default';
ALTER TABLE tags ADD COLUMN namespace TEXT NOT NULL DEFAULT 'default';
