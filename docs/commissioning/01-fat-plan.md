# Factory acceptance test (FAT) plan

Status: written 2026-10-14. Nothing in the result column is filled in unless it says when it was run and by what. The read-only
commands below were each run once to confirm they work; the steps that change something (pressing a button, stopping a
container) have not yet been run as part of this plan. Every expected result is either measured (the finding is named) or marked
as expected until a run confirms it.

## What this is, and what it is not

**Commissioning** is bringing a system into service and proving it does what was agreed. A **factory acceptance test (FAT)** is a
checklist run where the system was built, before it ships: each test gives its steps, what should be seen, and pass or fail. A
**site acceptance test (SAT)** is the same idea run at the customer's site, against the real equipment.

Our "factory" is one PC running the platform against a simulator. So this FAT shows that the **platform software** (gateways, tag
model, history, alarms, tickets, downtime, KPIs, deployment tooling) behaves correctly against a simulated plant. It cannot show
anything about real inverters, meters, networks or security hardening; those belong to a SAT (see "What a SAT would add").

## How to read a test

Each test has an **ID**, what it **proves**, the **steps**, the **pass criteria**, and **where to look**. Steps run in PowerShell in
the repo folder unless they say otherwise. The REST API cannot read tag values (finding 17), so anything about a live value is
checked on a Perspective page or in Designer; everything else can be checked from the command line.

Times: the alarm journal stores local time (America/Chicago) with no zone, the CMMS stores UTC, and the `downtime_intervals`
view converts. A ticket's `fault_started_at` and a journal row's `eventtime` for the same fault therefore differ by the zone
offset (five hours in October) and agree to within a second once that is taken into account.

## Before you start

1. `docker.exe compose up -d --build` and wait until `docker.exe compose ps` shows every container healthy.
2. The simulated plants must be in daylight for the plant-behavior tests. `SIM_START` in `.env` pins where each simulator's
   clock starts, and the clock stalls while the PC sleeps, so if a page shows night or low sun, run
   `docker.exe compose restart sim sim2` (README, Quick Start).
3. Each new Perspective session shows the Maker "Personal Use Only" notice; a person clicks Agree and Close.
4. Site 1's pages are at `http://localhost:8091/data/perspective/client/site` (pages `/`, `/trends`, `/controller`, `/faults`,
   `/downtime`); Site 2's are the same on port 8092; the fleet overview is
   `http://localhost:8090/data/perspective/client/fleet`; the mock CMMS is `http://localhost:8100`.

## The tests at a glance

| ID | Proves | Result |
|---|---|---|
| P1 | All 13 containers are up and healthy | Passed 2026-10-14 (13 of 13 healthy, start of the session) |
| P2 | Every gateway answers with its own key, is named for its port, has no problems and has its projects; the CMMS answers | Passed 2026-10-14 (13 of 13 checks, exit code 0) |
| P3 | The three test suites pass here and on a clean machine (CI) | Passed 2026-10-14 (generator 265, simulator 156, cmms 23; CI green on `eb625b0`) |
| C1 | Each gateway matches its points list (devices, connection, instances): no drift | Passed 2026-10-14 (all eight points lists: every line unchanged) |
| C2 | A raw register becomes the right engineering value (scale factors) | Not run |
| B1 | At midday the inverters clip at their rating with no limit active | Passed 2026-10-14 (5.00 MW at 896 W/m2, four inverters at 1,250 kW Throttled, no limit active) |
| B2 | A plant limit curtails the inverters evenly, and releasing it restores them | Passed 2026-10-14 (2.50 MW, each inverter 625 kW, "Yes, curtailing", Curtailed; released: back to 5.00 MW) |
| A1 | An inverter trip travels end to end: alarm, ticket, escalation, journal, downtime reason, KPIs | Passed 2026-10-14 (one ticket 0.43 s after the fault, one notification at 120.007 s, three journal rows, reason saved, KPIs and the fleet page agree; see the notes under the run log) |
| F1 | A ticket survives a short CMMS outage and is created once, with the true start time | Passed 2026-10-14 (one ticket, #6, delivered 28.08 s after the fault; its start time matches the journal's Active time within 0.1 s) |
| F2 | A stopped OEM-integrated site shows as not reporting and the fleet totals follow | Passed 2026-10-14 (7 of 8 reporting, output down 3.11 MW against OEM6's last 3.18 MW, rating unchanged, card "No data", back to 8 of 8 within 22 s of the restart) |
| S1 | A committed secret would be caught | On record (the gitleaks trials in the commits that added the scan; CI green) |
| R1 | The whole fleet rebuilds from an empty state with the README steps | Not run |

## Platform

### P1: containers
Steps: `docker.exe compose ps`.
Pass: 13 containers (hub, site1, site2, postgres, cmms, sim, sim2, oem1 to oem6), each `healthy`.

### P2: the status command
Steps: `python -m generator.status`, then `echo $LASTEXITCODE`.
Pass: the last line reads `all 13 checks passed` and the exit code is 0. The command asks each gateway (read-only) whether it
accepts its own API key, reports the right name for its port, lists no problems of its own, and has its projects present and
enabled, and asks the CMMS for `/health`. A crossed published port shows as a refused key or a wrong name (finding 71).

### P3: test suites and CI
Steps:
```
python -m unittest discover -s sim/tests -t .
python -m unittest discover -s generator/tests -t .
python -m unittest discover -s cmms/tests -t .
```
and look at the marks on the latest commit on GitHub (Actions tab: `tests` and `secret scan`).
Pass: each suite ends `OK` (skips only for packages that are not installed locally, see the README) and both marks are green.

## Communications

### C1: no drift
Steps: for each of `site1`, `site2`, `oem1` to `oem6`: `python -m generator.apply points/<name>.csv --dry-run`.
Pass: every line says `unchanged`. A dry run changes nothing; any other word names an object that differs from its points list.

### C2: scale factors (by hand)
Steps: in Designer's tag browser open `Inverters/Inv1`. Read `Raw/W`, `Raw/W_SF` and `ACPower_kW` within a few seconds of each
other (at a steady clipped midday value they do not move). The register layout is in `docs/points/site1-register-map.md`.
Pass: `ACPower_kW` equals `Raw/W` times 10 to the power `Raw/W_SF`, divided by 1000, within rounding; quality is Good.

## Plant behavior

### B1: clipping, no limit
Preconditions: midday (sunlight on the panels above about 900 W/m2), all four Site 1 inverters running, no limit enabled.
Steps: open the Site 1 overview.
Pass (expected; four inverters at 1,250 kW each in the state Throttled were observed on 2026-10-14): each inverter shows
1,250 kW and the state Throttled, the plant output is 5.0 MW, and the header says POWER LIMIT None active. Output sitting
exactly at the rating with no limit active is clipping, not curtailment.

### B2: curtailment by a plant limit
Preconditions: as B1.
Steps: on the Controller page enter 2.5 MW under "Active power limit" and switch "Limit enabled" on; wait a few seconds; read the
tiles; then switch the limit off.
Pass (expected from the 2026-10-05 run, to be confirmed): plant output 2.5 MW, each inverter 625 kW, "Is the limit cutting
output?" reads Yes, "Plant status" reads Curtailed; after the limit is switched off the inverters return to 1,250 kW.

## Alarm chain

### A1: an inverter trip, end to end
Preconditions: midday, Site 1 healthy (P2 passes), and no old unacknowledged alarm in the Alarms table (a fault that has cleared
but was never acknowledged stays listed, is acknowledged by the same action as the new one, and then dominates the mean time to
acknowledge; see the notes under the run log). Before you begin, note the number of tickets
(`(Invoke-RestMethod http://localhost:8100/tickets).Count`), the newest notification id and the Site 1 `fault_events` value, using:
```
docker.exe compose exec -T postgres psql -U fleet -d fleet -c "SELECT id, created_at, site, event_id FROM notifications ORDER BY id DESC LIMIT 3;"
docker.exe compose exec -T postgres psql -U fleet -d fleet -c "SELECT site, fault_events, mean_time_to_acknowledge_s, availability_percent FROM site_kpis;"
```
Steps and pass criteria:
1. On the Faults page press the **Trip inverter** button for Inv2. Within about a second its card shows 0 kW and the state Fault, and
   the Alarms table shows `InverterFault` Active and Unacknowledged. (The order goes over OPC UA; the result comes back over
   Modbus. Finding 72.)
2. The CMMS has exactly one new ticket for `site1`, `Inv2`, created within about a second of the trip (0.13 s on Site 1 in the
   2026-10-13 run, finding 78): `(Invoke-RestMethod http://localhost:8100/tickets)[0]`.
3. Do not acknowledge. About two minutes after the trip (120 s in the 2026-10-14 run) the `notifications` query above shows
   exactly one new row for `site1`, and its `event_id` equals the alarm's `eventid` in the journal (step 5).
4. Acknowledge the alarm in the Alarms table, then press **Clear fault**. The card returns to normal output.
5. The journal holds three rows with one shared `eventid`: Active (`eventtype` 0), Cleared (1) and Acknowledged (2):
   `docker.exe compose exec -T postgres psql -U fleet -d fleet -c "SELECT eventid, eventtype, eventtime FROM alarm_events_site1 WHERE source LIKE '%InverterFault' ORDER BY eventtime DESC LIMIT 6;"`
6. On the Downtime page the fault is listed with the reason `UNASSIGNED`. Choose a reason; it is saved at once. Then
   `docker.exe compose exec -T postgres psql -U fleet -d fleet -c "SELECT site, equipment, started_at, cleared_at, acknowledged_at, reason_code FROM downtime_intervals ORDER BY started_at DESC LIMIT 3;"`
   shows the chosen reason code on that fault, with `cleared_at` and `acknowledged_at` filled in.
7. The `site_kpis` query shows `fault_events` one higher than before, and the Reliability row for `site1` on the fleet page shows
   the same after a reload. (The numbers were recomputed independently in the earlier build, finding 81.)

## Failure behavior

### F1: the CMMS is down during a trip
Steps: `docker.exe compose stop cmms`; trip Inv3 on the Faults page; wait about 20 seconds;
`docker.exe compose start cmms`; wait up to a minute; clear the fault.
Pass (expected from the 2026-10-13 run, finding 79): exactly one new ticket appears after the CMMS is back (28 s after the fault
in that run), and its `fault_started_at` is the time of the trip, not the time of delivery. An outage much longer than the retry
window (60 tries, about a second apart) loses the ticket; that is a known limit (ADR 0019), not a failure of this test.

### F2: an OEM-integrated site stops
Steps: note the fleet page's FLEET OUTPUT, FLEET RATING and SITES tiles; `docker.exe compose stop oem6`; wait about a minute and
read the tiles and the OEM6 card; `docker.exe compose start oem6`; wait about a minute.
Pass (confirmed 2026-10-14): SITES reads `7 of 8 reporting`; FLEET OUTPUT falls by the output OEM6 was showing (up to 7.5 MW at
midday); FLEET RATING stays 47.5 MW because it is a stored sum of nameplates, not a measurement; the OEM6 card shows `No data`,
not an old number; within about a minute of the restart SITES reads `8 of 8 reporting` again.

## Security and rebuild

### S1: a committed secret is caught
Evidence on record: CI runs `secret scan` (gitleaks v8.30.1 with two rules for the Ignition token shapes) on every push, and the
pre-commit hook `scripts/check_secrets.py` runs before every commit. The gitleaks trials (planted fake tokens: 40 of 40 and 80
of 80 found with the project's rules against none found by the default rules; the real history clean) are in the commit
messages of `0cbe9b6` and `707d54c`.
To repeat: `python -m unittest generator.tests.test_check_secrets` and look at the `secret scan` mark on the latest commit.
Pass: the unit tests are OK and the mark is green. This checks the shapes and your own `.env` values; it cannot see a secret of
a shape nobody wrote a rule for.

### R1: rebuild from empty
Steps: follow the README Quick Start (steps 1 to 7) on a machine with no gateway volumes, then P2 and A1.
Pass: P2 passes and A1 passes with no manual repair beyond the README's one manual step (the `API_RW` level and API key).
Not performed for the whole fleet. Site 2 was rebuilt from an empty gateway by these steps on 2026-10-06 (finding 51).

## Not covered by this plan

- A database outage: the historian's behavior with PostgreSQL down, and the escalation script, which logs and does not retry
  (ADR 0018), are untested.
- A gateway restart while a ticket retry waits, and a fault that is active across a restart (ADR 0019).
- Loss of the link between a site gateway and the hub, and loss of a whole site gateway.
- Faults other than an inverter trip (comms loss, underperformance, battery faults), several faults at once, and the one-hour
  overlap when the clocks go back.
- Anything about real equipment (see below).

## What a SAT would add

At a real site the same tests would be run against real devices, and these things change: the Modbus unit IDs and register
addresses are checked point by point against the vendor's own register map instead of the simulator's; the Gateway Network moves
from plaintext to SSL with approved certificates (ADR 0004); the pages and the CMMS get logins; the escalation delay becomes
minutes instead of two; and tag quality, time sync and alarm routing are checked against the real network. Those are written up
separately when that piece is done.

## Run log

| Date | Run by | Tests | Notes |
|---|---|---|---|
| 2026-10-14 | the agent | P1, P2, P3, C1 | The commands above, as listed in the table. |
| 2026-10-14 | the agent and the tester | B1, B2, A1, F1, F2 | Measured values in the notes below. |

### Notes from the 2026-10-14 run

- **B1.** After restarting the simulators: plant output 5.00 MW, sunlight 896 W/m2, POWER LIMIT None active, every inverter
  1,250 kW in the state Throttled.
- **B2.** With 2.5 MW entered and the limit switched on: plant output 2.50 MW, each inverter 625 kW, "Is the limit cutting
  output?" Yes, "Plant status" Curtailed, POWER LIMIT "Limiting output". The simulator log showed the number arriving first
  (limit 2.500 MW, enabled False) and the switch about 19 s later (enabled True). After the switch was turned off: 5.00 MW and
  1,250 kW per inverter again. The state label is Throttled both when clipping and when curtailing, so only the limit indicator
  tells them apart.
- **A1, Inv2 on site1.** Ticket 5 was created 0.43 s after the fault's own timestamp (`fault_started_at` 00:11:38.193Z,
  `created_at` 00:11:38.625Z). The journal's Active row is 19:11:38.605 local, 0.41 s after that timestamp. The escalation wrote
  notification 3 at 120.007 s after Active. The three journal rows (Active, Acknowledged 19:15:27.424, Cleared 19:15:32.669) share
  one `eventid`. After a reason was chosen on the Downtime page, `downtime_intervals` showed `INV_FAULT` with `cleared_at` and
  `acknowledged_at` set. `site_kpis` for site1 went from 1 to 2 fault events, and the fleet page's Reliability row for site1 read
  2 events, mean time to acknowledge 3 h 35 min, mean time active 37 min 25 s, availability 98.70 %, the same as the query.
- **A finding from A1.** The journal rose by four rows, not three. The same Acknowledge action also acknowledged the earlier Inv1
  alarm, which had cleared at 13:18 but was never acknowledged, so its acknowledge time (19:15:27) came six hours after it
  cleared and dominated the mean time to acknowledge (3 h 35 min). The system behaved as designed: an alarm that has cleared but
  is unacknowledged stays in the table until a person acknowledges it. The A1 precondition now says to start with no old
  unacknowledged alarms. That old fault still has the reason `UNASSIGNED`, which counts against availability.
- **F1, Inv3 on site1.** With the CMMS stopped, Inv3 was tripped at 19:22:17 local (journal Active row 19:22:17.283) and the CMMS
  was started again after the planned wait of about 20 s. Exactly one new ticket arrived, #6 for site1 Inv3, 28.08 s after the fault: `fault_started_at`
  00:22:17.181Z (19:22:17.181 local, 0.10 s before the journal's Active row) and `created_at` 00:22:45.258Z. No second ticket
  appeared, and the notification count stayed at 3 because the alarm was acknowledged inside two minutes (19:23:02) and cleared
  at 19:23:06. The ticket carries the time of the trip, not the time it was delivered, which is what the retry design promises.
- **F2, oem6.** The fleet page was recorded every 5 s while oem6 was stopped (at 19:26, to the minute) and started again (19:28:25).
  In the last snapshot before the first "No data" one, fleet output was 22.00 MW and the OEM6 card showed 3.18 MW; in the next
  snapshot (19:26:47) SITES read `7 of 8 reporting`, fleet output was 18.89 MW (down 3.11 MW; the other sites also drift a few
  tenths of a MW every 5 s with the simulated clouds), FLEET RATING was still 47.5 MW, and the OEM6 card read "No data" with the
  line "No good reading from this site's meter", with no old number left on it. SITES returned to `8 of 8 reporting` in the
  snapshot at 19:28:47, 22 s or less after the start. Because the stop time was noted only to the minute, how quickly the page
  noticed the stop is not measured. Restarting a simulator puts its clock back to `SIM_START`, so OEM6 then read 7.50 MW at 894 W/m2
  (midday), while oem1 to oem5, which were not restarted, kept their own clocks (OEM6 itself had read about 357 W/m2 before its
  restart); restart them too when all the OEM sites should be at midday.
