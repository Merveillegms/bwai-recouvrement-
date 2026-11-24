-- Résolution humaine des anomalies d'import et clôture des factures en doublon.

ALTER TABLE import_anomalies ADD COLUMN resolution TEXT
    CHECK (resolution IS NULL OR resolution IN ('ignoree', 'remplacee'));
ALTER TABLE import_anomalies ADD COLUMN motif_resolution TEXT;
ALTER TABLE import_anomalies ADD COLUMN resolu_par TEXT;
ALTER TABLE import_anomalies ADD COLUMN resolu_le TEXT;

ALTER TABLE factures ADD COLUMN motif_cloture TEXT;

CREATE INDEX idx_anomalies_import ON import_anomalies(import_id);
