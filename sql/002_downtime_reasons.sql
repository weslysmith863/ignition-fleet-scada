-- Downtime reason codes and the operator's choices (ADR 0020). Two tables:
--   downtime_reasons             the list of codes, and whether each counts against availability (our design choice; real
--                                contracts differ, and the flags can be changed here)
--   downtime_reason_assignments  the reason an operator gave for one alarm's downtime, keyed by the alarm event's id (the same
--                                value as the journal's eventid, a UUID, so it identifies the alarm across every site)
-- The downtime intervals themselves are not stored here: a view over the alarm journal tables builds them (sql/003).
-- Safe to run more than once: the seed rows are brought back to this file's values on every run. Apply with:
--   docker.exe compose exec -T postgres psql -U fleet -d fleet -v ON_ERROR_STOP=1 -f - < sql/002_downtime_reasons.sql
CREATE TABLE IF NOT EXISTS downtime_reasons (
    code                        text PRIMARY KEY,
    description                 text NOT NULL,
    counts_against_availability boolean NOT NULL,
    sort_order                  integer NOT NULL
);

INSERT INTO downtime_reasons (code, description, counts_against_availability, sort_order) VALUES
    ('UNASSIGNED',    'No reason chosen yet',               true,  0),
    ('INV_FAULT',     'Inverter fault',                     true,  1),
    ('EQP_OTHER',     'Other equipment failure',            true,  2),
    ('GRID',          'Grid outage',                        false, 3),
    ('CURTAIL',       'Utility curtailment order',          false, 4),
    ('WEATHER',       'Severe weather',                     false, 5),
    ('MAINT_PLANNED', 'Planned maintenance',                false, 6)
ON CONFLICT (code) DO UPDATE SET
    description = EXCLUDED.description,
    counts_against_availability = EXCLUDED.counts_against_availability,
    sort_order = EXCLUDED.sort_order;

CREATE TABLE IF NOT EXISTS downtime_reason_assignments (
    event_id    text PRIMARY KEY,
    reason_code text NOT NULL REFERENCES downtime_reasons (code),
    assigned_by text NOT NULL DEFAULT 'unknown',
    assigned_at timestamptz NOT NULL DEFAULT now(),
    note        text
);
