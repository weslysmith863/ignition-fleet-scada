-- The sites that have alarm journals, and how many inverters each has (ADR 0021). The KPI view needs the inverter count to turn
-- "minutes of fault" into an availability percentage, and needs a row for a site that has had no faults at all, which the
-- downtime view cannot give (it only has rows for faults). The OEM-integrated sites are not here: they have no plant controller,
-- no inverter-fault alarm and no journal yet (ADR 0015, ADR 0017).
-- Keep this in step with the points lists: generator/tests/test_sql.py fails if a site's inverter count here differs from the
-- inverter rows in points/<site>.csv. Safe to run more than once. Apply with:
--   docker.exe compose exec -T postgres psql -U fleet -d fleet -v ON_ERROR_STOP=1 -f - < sql/004_sites.sql
CREATE TABLE IF NOT EXISTS sites (
    site           text PRIMARY KEY,
    inverter_count integer NOT NULL CHECK (inverter_count > 0)
);

INSERT INTO sites (site, inverter_count) VALUES
    ('site1', 4),
    ('site2', 6)
ON CONFLICT (site) DO UPDATE SET inverter_count = EXCLUDED.inverter_count;
