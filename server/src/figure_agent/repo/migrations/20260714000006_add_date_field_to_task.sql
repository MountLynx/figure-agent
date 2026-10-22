-- Add a date field to the "任务" preset type (id=2) if it doesn't already exist
INSERT INTO fields (type_id, name, field_type, icon, position, label)
SELECT 2, '截止日', 'date', 'calendar',
       (SELECT COALESCE(MAX(position), -1) + 1 FROM fields WHERE type_id = 2),
       '截止日'
WHERE NOT EXISTS (SELECT 1 FROM fields WHERE type_id = 2 AND name = '截止日');
