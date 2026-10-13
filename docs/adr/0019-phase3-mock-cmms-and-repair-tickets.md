# ADR 0019: A mock CMMS that receives repair tickets from Event Streams

Status: Accepted (2026-10-13). Wes approved the recommendations below. The container is built and tested, and Wes hand-built the
Event Stream that feeds it in Designer (the section "The Event Stream as built" below); it ran end to end on site1 on 2026-10-13
(a trip of Inverter 4 became ticket 1, 0.13 s after the trip event). It was carried to site2 with `deploy_project` and ran there too (ticket 2). Wes has not reviewed
the written ADR yet.

## Context

Phase 3's gate is "fault scenarios run end to end": a fault raises an alarm that reaches a ticket and a downtime row. The ticket
needs somewhere to go. A CMMS (computerized maintenance management system) is where repair work is tracked; we have none, and
this is a personal project on Maker, so the CMMS is a small stand-in. It also exercises an Event Stream with an HTTP handler,
which no earlier phase used (Phase 0 used the database handler).

## Decision

1. **The ticket is created when the fault starts,** not after the escalation of ADR 0018. A tripped inverter needs a repair job
   whether or not anyone acknowledges the alarm. The escalation is about attention and the ticket is about repair, so the two run
   separately.
2. **The trigger is a Tag Event source on the inverter's status (`Inverter/Raw/St`), filtered to the value 7 (Fault).** The 8.3
   documentation lists four Event Stream sources (Kafka, HTTP Endpoint, Event Listener, Tag Event) and no plain alarm-event
   source, so an Event Stream cannot start from the alarm's event id. This comes from the documentation and has not been checked
   against this gateway's source list.
3. **One ticket per fault, keyed by site, equipment, and the time the fault started** (the status tag's timestamp). A request that
   arrives twice, for example after a retry, makes one ticket and the second answer returns the first (HTTP 200 instead of 201).
   Properties like this are called idempotent. The start time is normalized to UTC, so epoch milliseconds and an ISO-8601 time
   for the same instant are one fault; a time with no zone is refused.
4. **The CMMS is a FastAPI service in a container named `cmms`,** `cmms/` in the repo, built like the simulator (repo-root build
   context, non-root user, health check). It listens on 8000 inside the Compose network, so the gateways post to
   `http://cmms:8000/tickets`; its page and its interactive documentation (`/docs`) are published on this PC's loopback as 8100.
   FastAPI and uvicorn were added as new downloads with Wes's approval, and every package is pinned (each at least 14 days old
   when pinned).
5. **Tickets are kept in the CMMS's own SQLite file** on the `cmms-data` volume, not in `fleetdb`, as a real maintenance system
   would keep its own records. The ticket logic is a standard-library module, so most of it is tested without FastAPI.
6. **The request body is read as JSON whatever Content-Type the sender declares,** so a first HTTP handler that forgets the header
   still works. Required fields are `site`, `equipment` and `fault_started_at`; `priority` defaults to High (the D70 scheme) and
   `summary` to a generated line; unknown fields are ignored.
7. **Ticket numbers have no gaps after a repeat.** SQLite uses up a number for an insert that is ignored as a duplicate, so the
   store looks for the existing ticket first and inserts only a new one; the unique key stays as the backstop.

## The Event Stream as built

The stream `InverterFaultTicket` is in the `site` project, so it runs on every site gateway; its `config.json` is readable JSON
under `projects/site/com.inductiveautomation.eventstream/`.

- **Source:** Tag Event on `[default]Inverters/*/Raw/St` (a wildcard, so one stream covers every inverter on a gateway), triggering
  on Value only. Initial values are not skipped, so each matching tag fires once whenever the stream starts.
- **Filter:** keeps only events whose value is 7 (Fault).
- **Transform:** builds the ticket from the event: `equipment` is the second part of the tag path (`Inv4`), `site` is the
  gateway's system name (`[System]Gateway/SystemName`), `fault_started_at` is the tag's own timestamp in epoch milliseconds,
  `priority` is High (written into the script to match the `InverterFault` alarm's priority), and `summary` is a sentence.
- **Handlers:** a Logger that prints the ticket body (kept so a person can see what is sent), then an HTTP handler that POSTs
  that body to `http://cmms:8000/tickets` over HTTP/1.1 with `Content-Type: application/json`.
- **Failure strategy:** the Logger stays on ABORT. The HTTP handler is on RETRY, Fixed, 60 tries, a Retry Delay of 1000, and
  Retry Failure ABORT. A retry is safe because the CMMS ignores duplicates. Fixed and not Exponential, because Max Delay accepts
  at most 1000 ms, so an exponential wait could never exceed a second. The Retry Delay field is labeled seconds but behaved as
  milliseconds (finding 79). Tested by stopping the CMMS for about 20 s: the ticket arrived once, 28 s after the fault, still
  carrying the true fault start time.

## Consequences

- Both site gateways post to the same CMMS. A ticket is identified by the site name in the body, so the Event Stream must send
  the gateway's system name.
- The status tag's timestamp may be re-stamped when a gateway restarts and re-reads the device, so a fault that is still active
  across a restart could produce a second ticket (a guess, not tested).
- Closing a ticket, assigning it, and linking it to downtime rows are not built; the table has a `status` column (always `open`
  for now) so they can be added.
- There is no login on the CMMS: the Compose network and the loopback port are the only protection, a development relaxation like
  those in ADR 0004.
- A script error in the Filter or Transform does not stop the stream: the stream stays RUNNING, the stage stays GOOD, and each
  event is dropped and counted in the stage's error list. A configuration error in a handler stops the whole stream (FAULTED),
  and events that happen while it is stopped are not replayed (finding 77). Anything that monitors this stream must read the
  stage error counts and the stream state, not only whether it is running.
- Retries wait in the gateway's memory. A CMMS outage longer than the retry window, or a gateway restart during it, still loses
  the ticket (untested for the restart). When the retries run out the handler's Retry Failure is ABORT, which should run the
  stream's Error Handler stage, still empty; a durable fallback (saving the failed ticket to a table to resend) would go there.
- Starting or saving the stream fires every matching tag once, so a fault that is already active when the stream starts gets
  a ticket, keyed by the tag's timestamp. Whether the timestamp survives a gateway restart is untested.
- The stream is carried to the repo the way the pipeline was (ADR 0018, finding 74), and to site2 with `deploy_project`.
