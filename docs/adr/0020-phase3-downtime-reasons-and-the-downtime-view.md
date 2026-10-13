# ADR 0020: Downtime reason codes and the downtime view

Status: Accepted (2026-10-13). Wes approved decisions 1 to 3 below ("recs good"). Wes first planned to write the view himself, then
decided the same day that the SQL learning was too much to take on right now and asked the agent to write it; the agent did, and
explained it step by step in the SQL file. Wes has not reviewed the written ADR yet.

## Context

Phase 3's gate needs a downtime record: which equipment was down, for how long, and why. The "why" matters because availability
(the share of time equipment was able to produce) usually leaves out causes that are not the plant's fault, such as a grid outage.
The alarm journal already holds every inverter fault with its start, acknowledge and clear times (finding 72).

## Decision

1. **Downtime is an inverter fault interval, from the alarm's Active to its Cleared.** This is an approximation: the clock stops
   at Clear, not when the inverter is producing again. Other causes (comms loss, curtailment, battery) join when those faults are
   built.
2. **Intervals are not stored.** A view, `downtime_intervals` (`sql/003_downtime_view.sql`), builds one row per alarm from the
   per-site alarm journal tables, so a new fault appears by itself and the journal stays the single source of truth. What is
   stored is the operator's choice of reason, in `downtime_reason_assignments`, keyed by the alarm event's id, which is a UUID and
   so identifies the alarm across sites (`sql/002_downtime_reasons.sql`).
3. **Seven reason codes, each with a flag for whether it counts against availability:** `UNASSIGNED`, `INV_FAULT` and `EQP_OTHER`
   count; `GRID`, `CURTAIL`, `WEATHER` and `MAINT_PLANNED` do not. The split is our own design choice, not sourced, and real
   contracts differ; the flags are changed by editing the seed rows in `sql/002` and running the file again. A fault nobody has
   given a reason shows as `UNASSIGNED`.
4. **A fault that has not cleared** has a NULL `cleared_at`, `ongoing` true, and a duration measured up to now.
5. **The journal's times are converted in the view.** The journal stores local time (America/Chicago) with no time zone; the view
   turns it into a real timestamp so it compares with the CMMS and the historian, which use UTC or epoch time.
6. **The site comes from which journal table a row is in,** because the journal has no site column. The view stacks `site1` and
   `site2` by hand; a third site means adding a branch (the generator could build it).

## Consequences

- The view and its two tables are created only when the SQL files are run; nothing applies them after a database rebuild yet (the
  same gap as `notifications`, ADR 0018).
- The time conversion assumes the gateways run in America/Chicago, as `TZ` says in `docker-compose.yml`. The one-hour ambiguity
  when the clocks go back (2026-11-01) was not tested.
- An alarm that was cleared and never acknowledged shows with a NULL `acknowledged_at` (one old test alarm does).
- Availability itself and the other KPIs are not computed yet; the view gives them their inputs.
- The Downtime page that shows the view and saves a reason is the next piece; the reason is saved with the acknowledging user
  unknown, as in the journal, because the pages have no login (ADR 0004).
