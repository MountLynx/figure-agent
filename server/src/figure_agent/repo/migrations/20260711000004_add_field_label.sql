-- Add label column to fields table for checkbox display text
ALTER TABLE fields ADD COLUMN label TEXT NOT NULL DEFAULT '';
