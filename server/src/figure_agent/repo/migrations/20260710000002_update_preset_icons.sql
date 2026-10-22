-- Safety migration: update legacy emoji icons to Tabler icon names
-- No-op for new repos (v1 already uses Tabler names)
UPDATE item_types SET icon = 'file' WHERE id = 1 AND icon = '📄';
UPDATE item_types SET icon = 'checkbox' WHERE id = 2 AND icon = '✅';
