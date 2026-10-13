-- The downtime intervals (ADR 0020): one row per inverter-fault alarm, built from the alarm journal. Nothing is stored here: the
-- view is a saved query, so it reads the journal tables again every time it is asked, and a new fault shows up by itself.
--
-- Columns:
--   site                         'site1' or 'site2'. The journal has no site column: the site is which TABLE a row lives in,
--                                so each branch of the UNION ALL below stamps its own name on its rows.
--   equipment                    the inverter, for example 'Inv4', taken from the alarm's source path
--   event_id                     the alarm event's id (the journal's eventid; also what the reason table is keyed by)
--   started_at                   when the alarm became Active
--   cleared_at                   when it Cleared; NULL while the fault is still going on
--   acknowledged_at              when a person Acknowledged it; NULL if nobody has
--   ongoing                      true while the fault has not cleared
--   duration                     cleared_at - started_at; for a fault that has not cleared, the time since it started
--   reason_code, reason_description, counts_against_availability
--                                the operator's choice from downtime_reason_assignments, or UNASSIGNED if none, with the
--                                code's description and flag from downtime_reasons
--
-- How it works, step by step:
--   journal  stacks the two sites' journal tables into one list, stamping each row with its site.
--   folded   keeps only the InverterFault alarm rows, puts the rows of each alarm (one eventid) into a pile, and turns the
--            three rows of a pile (Active 0, Acknowledged 2, Cleared 1) into one row with three time columns. MIN ignores the
--            empty cells that CASE leaves, so each column ends up with the one real time.
--   The last SELECT converts the journal's times (local time with no time zone, America/Chicago) into real timestamps, and
--   adds the reason, using the code UNASSIGNED when nobody has chosen one.
--
-- Safe to run more than once (CREATE OR REPLACE VIEW). Adding a third site means adding a third branch to journal. Apply with:
--   docker.exe compose exec -T postgres psql -U fleet -d fleet -v ON_ERROR_STOP=1 -f - < sql/003_downtime_view.sql
CREATE OR REPLACE VIEW downtime_intervals AS
WITH journal AS (
    SELECT 'site1' AS site, eventid, source, eventtype, eventtime FROM alarm_events_site1
    UNION ALL
    SELECT 'site2' AS site, eventid, source, eventtype, eventtime FROM alarm_events_site2
),
folded AS (
    SELECT site,
           eventid,
           substring(min(source) FROM '/tag:Inverters/([^/]+)/') AS equipment,
           min(CASE WHEN eventtype = 0 THEN eventtime END) AS started_local,
           min(CASE WHEN eventtype = 2 THEN eventtime END) AS acknowledged_local,
           min(CASE WHEN eventtype = 1 THEN eventtime END) AS cleared_local
    FROM journal
    WHERE source LIKE '%/alm:InverterFault'
    GROUP BY site, eventid
    HAVING min(CASE WHEN eventtype = 0 THEN eventtime END) IS NOT NULL
)
SELECT f.site,
       f.equipment,
       f.eventid AS event_id,
       f.started_local AT TIME ZONE 'America/Chicago' AS started_at,
       f.cleared_local AT TIME ZONE 'America/Chicago' AS cleared_at,
       f.acknowledged_local AT TIME ZONE 'America/Chicago' AS acknowledged_at,
       f.cleared_local IS NULL AS ongoing,
       COALESCE(f.cleared_local AT TIME ZONE 'America/Chicago', now()) - (f.started_local AT TIME ZONE 'America/Chicago') AS duration,
       r.code AS reason_code,
       r.description AS reason_description,
       r.counts_against_availability
FROM folded f
LEFT JOIN downtime_reason_assignments a ON a.event_id = f.eventid
JOIN downtime_reasons r ON r.code = COALESCE(a.reason_code, 'UNASSIGNED');
