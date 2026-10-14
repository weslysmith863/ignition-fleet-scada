-- Reliability numbers per site for the last 24 hours (ADR 0021). One row per site in the sites table, read fresh every time.
--
--   fault_events                 inverter faults that STARTED in the period
--   mean_time_to_acknowledge_s   average seconds from a fault starting to a person acknowledging it (NULL if none was)
--   mean_time_active_s           average seconds a fault lasted, over faults that have cleared (NULL if none has)
--   counted_downtime_s           seconds of fault inside the period whose reason counts against availability. A fault that began
--                                before the period counts only from its start, and one still going on counts up to now.
--   availability_percent         100 * (1 - counted_downtime_s / (inverters * seconds in the period)), to 2 decimals.
--                                This is OUR simplification: time-based over all 24 hours. Real solar contracts often measure
--                                only daylight hours and have their own exclusions; the flags in downtime_reasons say which
--                                reasons are left out here.
--
-- How it works: period holds the 24-hour window; per_fault takes each downtime row and works out how many of its seconds fall
-- inside the window (GREATEST of the start and the window's start, to LEAST of the end and now); the last SELECT groups those
-- per site. FILTER (WHERE ...) restricts one aggregate to some rows, so one pass gives all the numbers.
--
-- The numbers are cast to double precision so Ignition's scripts receive plain floats and not exact decimals (Java BigDecimal).
--
-- Safe to run more than once: the view is dropped and created again, because CREATE OR REPLACE VIEW cannot change a column's
-- data type (which this file did once). Nothing depends on site_kpis in the database, so dropping it is harmless. Apply with:
--   docker.exe compose exec -T postgres psql -U fleet -d fleet -v ON_ERROR_STOP=1 -f - < sql/005_site_kpis.sql
DROP VIEW IF EXISTS site_kpis;
CREATE VIEW site_kpis AS
WITH period AS (
    SELECT now() - interval '24 hours' AS starts_at, now() AS ends_at
),
per_fault AS (
    SELECT d.site,
           d.event_id,
           d.started_at,
           d.acknowledged_at,
           d.ongoing,
           d.duration,
           d.counts_against_availability,
           extract(epoch FROM greatest(interval '0',
                   least(coalesce(d.cleared_at, p.ends_at), p.ends_at) - greatest(d.started_at, p.starts_at))) AS seconds_in_period
    FROM downtime_intervals d
    CROSS JOIN period p
)
SELECT s.site,
       s.inverter_count,
       24 AS period_hours,
       count(f.event_id) FILTER (WHERE f.started_at >= p.starts_at) AS fault_events,
       extract(epoch FROM avg(f.acknowledged_at - f.started_at)
               FILTER (WHERE f.started_at >= p.starts_at AND f.acknowledged_at IS NOT NULL))::double precision AS mean_time_to_acknowledge_s,
       extract(epoch FROM avg(f.duration)
               FILTER (WHERE f.started_at >= p.starts_at AND NOT f.ongoing))::double precision AS mean_time_active_s,
       coalesce(sum(f.seconds_in_period) FILTER (WHERE f.counts_against_availability), 0)::double precision AS counted_downtime_s,
       round((100 * (1 - coalesce(sum(f.seconds_in_period) FILTER (WHERE f.counts_against_availability), 0)
                         / (s.inverter_count * 24 * 3600.0)))::numeric, 2)::double precision AS availability_percent
FROM sites s
CROSS JOIN period p
LEFT JOIN per_fault f ON f.site = s.site
GROUP BY s.site, s.inverter_count, p.starts_at;
