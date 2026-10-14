# ADR 0021: Site KPIs and a time-based availability

Status: Accepted (2026-10-13). Wes approved all four decisions below ("recs good"). The agent wrote the SQL and the page, as
Wes asked for the SQL (ADR 0020). Wes has not reviewed the written ADR yet.

## Context

The downtime view (ADR 0020) holds every inverter fault with its times and its reason. Phase 3 needs numbers a manager can read
from it: how often faults happen, how fast people respond, how long faults last, and how much of the time the inverters were able
to produce (availability).

## Decision

1. **Four KPIs per site:** fault events, mean time to acknowledge, mean time active, and availability.
2. **The period is the last 24 hours, rolling.** A selectable range can come later.
3. **Availability is time-based over all 24 hours,** per inverter, averaged over the site:
   `100 * (1 - counted fault seconds / (inverters * 86400))`. Only faults whose reason counts against availability are counted
   (`downtime_reasons.counts_against_availability`), so a fault nobody has given a reason yet counts (`UNASSIGNED` counts). A fault
   that began before the period counts from the start of the period, and one still going on counts up to now. This is our own
   simplification: real solar contracts often measure only daylight hours and have their own exclusions.
4. **Where it is built.** The SQL view `site_kpis` (`sql/005_site_kpis.sql`) reads the downtime view and a small `sites` table
   (`sql/004_sites.sql`: each site and its inverter count). A test, `generator/tests/test_sql.py`, fails if the `sites` table
   disagrees with the inverter rows of the points lists, or the downtime view lacks a site's journal. The hub's fleet overview
   gets a "Reliability, last 24 hours" section, one row per site (`SiteKpiRow`), written as project files by the agent. A site
   with no alarm journal, such as the OEM-integrated sites, shows n/a and not an invented 100 percent.

## Consequences

- Mean time active is how long the alarm stayed active, which stands in for repair time; it averages only faults that have cleared.
- The numbers are only as good as the test data: today one 56-minute test fault from 2026-10-12 accounts for about 87 percent of
  site1's counted downtime, which is why site1 reads 98.87 percent.
- Only inverter faults count. Curtailment and other partial losses of output (a derate) are not downtime here; they would need
  production data against what the plant could have made.
- Adding a site means a new row in `sites` and a new branch in the downtime view; the test catches a forgotten one.
- The hub reads the same `fleetdb` database as the sites, so no data moves between gateways; the page re-reads every 30 seconds.
- The files in `sql/` are still applied by hand (ADR 0018, ADR 0020).
