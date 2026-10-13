# ADR 0018: Escalating an unacknowledged alarm with an alarm pipeline

Status: Accepted (2026-10-13). Wes approved the recommendations below and hand-built the pipeline in Designer. Wes has not
reviewed the written ADR yet.

## Context

Phase 3 needs an answer to "what happens after an alarm becomes active and nobody acknowledges it". The journal already records
who acknowledged and when (finding 72). This ADR adds the escalation. It is one alarm pipeline, a small flow that the gateway
starts for each alarm event, and it tests the pieces Maker allows before the later Event Streams and CMMS work relies on them
(finding 73).

## Decision

1. **The pipeline runs on the site gateway that owns the tag,** as D70 says, so a tripped inverter escalates even when the link to
   the hub is down (Wes's own reasoning). It still depends on the PostgreSQL database, which each site gateway reaches directly.
2. **The flow is START, then a Delay of 120 seconds, then a Script block.** Two minutes is a demonstration value. A real site
   would wait much longer, perhaps 10 to 15 minutes; that figure is our assumption, not sourced.
3. **The pipeline stops by itself, with no check block.** The pipeline's Dropout Condition (Acknowledged, Cleared, Shelved, all
   left ticked, the template's default) ends the pipeline for an event when any of them happens (finding 75 tested Acknowledged and
   Cleared). Shelved is the same mechanism and was not tested. A Cleared alarm no longer needs attention, and the journal still
   records it as cleared and unacknowledged.
4. **"Notify" is a row in the `notifications` table,** written by the Script block with `system.db.runPrepUpdate` on `fleetdb`
   (`sql/001_notifications.sql`; columns `site`, `event_id`, `source`, `priority`, `reason`, `message`). It stands in for an
   email or a pager, because there is no mail server; replacing it with real email changes only that block. Unlike the journal's
   tables, this table is ours, so it has a `site` column and every gateway writes the same one. `event_id` is the alarm event's id,
   the same value as the journal's `eventid`.
5. **The pipeline is named `UnackedEscalation` and lives in the `site` project,** which runs on every site gateway, so one
   pipeline serves both. The `InverterFault` alarm points at it through its Active Pipeline property on the Inverter UDT, so every
   inverter instance has it. The repo holds the pipeline as the exported binary files (finding 74); this ADR is the readable
   description.
6. **The repair ticket is a separate job.** Creating a CMMS ticket (Event Streams to a mock CMMS) is system-to-system integration
   and is not part of this pipeline. This pipeline only decides who is told, and when.

## Consequences

- If the database is down at the end of the wait, the script's `try`/`except` logs an error and the escalation is lost: there is
  no retry and no store-and-forward on that write. This follows from how the script is written and was not tested.
- A pipeline instance stays listed in the pipeline overview until its delay ends, even after the alarm is acknowledged (finding
  75), so the overview's instance count must not be shown as a count of unacknowledged alarms.
- The pipeline handles one case (High priority inverter trips, in practice). Different treatment per priority (Critical, Medium,
  Low, D70) would use a Switch block or the Priority template and is not built.
- The Notification blocks, notification profiles and on-call rosters are not used; none exist on the gateways.
- A Designer save retires and restarts the pipeline; repo deploys do the same through the REST API (finding 74).
