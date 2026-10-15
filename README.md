# Fleet SCADA on Ignition 8.3: Solar + BESS Fleet Platform

[![tests](https://github.com/weslysmith863/ignition-fleet-scada/actions/workflows/tests.yml/badge.svg)](https://github.com/weslysmith863/ignition-fleet-scada/actions/workflows/tests.yml)
[![secret scan](https://github.com/weslysmith863/ignition-fleet-scada/actions/workflows/secret-scan.yml/badge.svg)](https://github.com/weslysmith863/ignition-fleet-scada/actions/workflows/secret-scan.yml)

> **Personal learning project built on Ignition Maker Edition (non-commercial).**
> Not a product, not a customer deployment. Every device and site is simulated, and the numbers are illustrative.
> Ignition is a trademark of Inductive Automation. This project is not affiliated with or endorsed by Inductive Automation.

A SCADA platform for simulated utility-scale solar and battery storage (BESS) sites, built on Inductive Automation's
Ignition 8.3 and designed the way an integrator would: sites generated from templates and a points list, Python and SQL
underneath, and everything stored as files in Git and deployed through the gateway's REST API. It runs from Docker Compose.

## Status

**Phases 0 to 3 of 4 are built and working, and Phase 4 is under way.** Eight simulated sites run from their points lists, and
one kind of fault, an inverter trip, runs end to end: alarm, escalation, repair ticket, downtime record, and reliability numbers.
Every push is checked by CI: the tests on a clean machine, and a secret scan of the whole Git history.

| Phase | Goal | State |
|---|---|---|
| 0 | Spikes and skeleton: hub reads a tag from a site gateway | Done |
| 1 | One site end to end | Done |
| 2 | Fleet and templating: 8 sites from points lists, a battery model | Done |
| 3 | Operations layer: alarms, downtime, Event Streams, fault scenarios | Done for one fault type (the inverter trip); no new fault types for now |
| 4 | Admin tooling, CI, commissioning docs, showcase | In progress: CI, a secret scan, a read-only status check and a factory acceptance test plan (nine of its twelve tests run and passed) are done; the Build Brief and a demo video remain |

## What works today

- **Simulator** (`sim/`, Python 3): sun position, seeded clouds, module temperature, inverter clipping, a plant-level power
  limit, a revenue meter, a 2.5 MW / 10 MWh battery on site 1, and fault injection (an inverter trip ordered over OPC UA). It
  serves SunSpec Modbus TCP and an OPC UA plant controller from one process and one clock, as the `sim` and `sim2` containers
  (plus six more for the OEM-integrated sites).
- **Ignition tag model**: five UDT templates (Inverter, Weather, Meter, PlantController, Battery), with Modbus scale factors
  handled by expressions and the OPC UA values arriving in engineering units.
- **Fleet**: two site gateways and a hub. Eight sites are live from their points lists: two plants behind their own gateways
  and six OEM-integrated plants read by the hub directly, all visible on one fleet screen through remote and local tag providers.
- **Points-list generator** (`generator/`, standard library only): creates the Modbus devices, the OPC UA connection and the UDT
  instances, imports the saved UDT definitions, creates the PostgreSQL connection, the SQL Historian and the alarm journal,
  creates the hub's tag providers, deploys projects, retargets device hosts, and applies the SQL files. Each tool is a dry run
  or reports before it changes anything, and none overwrites hand-built objects.
- **CI and secret scanning** (`.github/workflows/`): GitHub Actions runs the three test suites on every push and pull request,
  on a clean machine, so the CMMS web-service tests and the OPC UA tests run there too. A second workflow scans the whole Git
  history with gitleaks, with two extra rules for Ignition's token shapes, and a pre-commit hook (`scripts/check_secrets.py`)
  checks for the values in your own `.env`.
- **Status check** (`generator/status.py`): `python -m generator.status` asks each gateway, read-only, whether it answers with
  its own API key, reports its own name, lists no problems and has its projects enabled, and asks the mock CMMS for `/health`.
- **The operations chain** (Phase 3, `docs/layer-cards/04-operations-layer.md`): a trip raises the `InverterFault` alarm, which
  is journaled in PostgreSQL; an alarm pipeline escalates it if nobody acknowledges within two minutes; an Event Stream posts one
  repair ticket per fault, with retry, to a mock CMMS container (`cmms/`, FastAPI and SQLite); an operator gives each fault a
  reason on a Downtime page; SQL views build the downtime records and per-site KPIs (fault events, mean time to acknowledge,
  mean time active, a time-based availability), shown on the hub's fleet screen.
- **Screens** (`projects/`): Perspective project files deployed with one command. `site` (the same files on every site gateway):
  Overview, Trends, Controller, Faults, Downtime. `fleet` (on the hub): the fleet overview with a Reliability section and a site
  detail page. `core` holds the shared views.
- **History and SQL**: SQL Historian on PostgreSQL, and five numbered SQL files in `sql/` (applied with
  `python -m generator.sqlfiles --apply`).
- **Documentation**: 21 architecture decision records, five layer cards, a domain primer, a factory acceptance test plan with
  its first measured results (`docs/commissioning/`), and findings logs of what the experiments showed, including the mistakes.
- **Tests**: 444 automated tests (156 simulator, 265 generator and tooling, 23 mock CMMS), standard library only. The five CMMS
  web-service tests and the three OPC UA simulator tests need extra packages and are skipped without them; CI installs those
  packages, so they run there.

## What it demonstrates

Hub and site gateway architecture, UDT and template-driven tag models, Modbus TCP and OPC UA connectivity against a realistic
simulator, solar and BESS domain concepts (clipping versus curtailment, point of interconnection, state of charge, availability),
alarm journals, pipelines and escalation, Event Streams with retry into an external system, downtime and KPI modeling in SQL,
secrets kept out of Git, Git-native project files, and gateway administration through the REST API. Where something is
simulated or simplified, the docs say so.

## Quick start

You need Docker Desktop, Python 3, and an [Ignition Maker Edition](https://inductiveautomation.com/ignition/maker-edition)
account with licenses for the gateways (one key and one activation token each, three gateways).

```
copy .env.example .env        # then fill in the values; .env is gitignored and never committed
docker compose up -d --build  # hub, site1, site2, postgres, cmms, the simulators
```

Then there is first-time setup on a fresh gateway. Only the first step is manual; each of the others is a tool that reports
before it changes anything (the full order, and the gotchas, are in `CLAUDE.md` and the findings):

1. In each gateway's web page, create a security level `API_RW`, allow it under *Gateway Write Permissions*, and create an API
   key that holds it. Put the tokens in `.env` (`HUB_API_TOKEN`, `SITE1_API_TOKEN`, `SITE2_API_TOKEN`). See `docs/adr/0005`.
2. `python -m generator.connections site1` creates the PostgreSQL connection `fleetdb` with an encrypted password, the SQL
   Historian provider `Historian`, and the alarm journal (add `--dry-run` to only report). Do the same for `site2` and `hub`
   as needed.
3. `python -m generator.import_types site1 --apply` creates the UDT definitions from `gateway/site1/udt-types.json`
   (without `--apply` it only reports).
4. `python -m generator.apply points/site1.csv` creates the Modbus devices, the OPC UA connection `PlantController`, and the
   UDT instances; `points/site2.csv` and the OEM files work the same way.
5. `python -m generator.sqlfiles --apply` creates the notifications, downtime and KPI tables and views (run it after the alarm
   journals exist, because the downtime view reads them).
6. `python -m generator.deploy_all` deploys the screens: `core` and `site` to each site gateway, `core` and `fleet` to the hub.
   The alarm pipeline and the Event Stream are resources of the `site` project, so they deploy with it. Then open
   `http://localhost:8091/data/perspective/client/site` (and `:8092`) for a site, or
   `http://localhost:8090/data/perspective/client/fleet` for the fleet overview. The mock CMMS is at `http://localhost:8100`.
7. `python -m generator.status` asks every gateway, without changing anything, whether it answers with its own API key, reports
   its own name, lists no problems, and has its projects enabled, and asks the mock CMMS for `/health`. It exits with 0 when every
   check passes and 1 otherwise. (The REST API cannot read tag values, so it says the gateways are up and configured, not that
   the plant is producing.)

`SIM_START` in `.env` pins the simulated start time (for example midday, so the plant is producing); empty means the real clock.

Run the tests with `python -m unittest discover -s sim/tests -t .`, `python -m unittest discover -s generator/tests -t .`, and
`python -m unittest discover -s cmms/tests -t .`.

## Known limits and dev-only choices

These are deliberate for a local, single-machine project, and each is written down so it is not mistaken for a design.

- **No security on local links**: plaintext Gateway Network and API key transport (ADR 0004), an OPC UA server with no security
  (ADR 0010), and Perspective screens and a mock CMMS with no login (ADR 0012, ADR 0019). A fault button writes straight to the
  simulator. The generator also gives a new OPC UA connection the default password for the gateway's own OPC client key store
  (Phase 2 finding 45), a dev default for a self-generated certificate. All ports are bound to the loopback interface. None of
  this is suitable for a shared deployment.
- **Open tag provider permissions**: the hub's local tag providers require no security level (finding 58), so the generator's API
  key can import tags. A real deployment would restrict read, write, and edit by role.
- **The simulator is a model**: what is modeled with sources, what is our own rule, and what is approximated is written down in
  Layer Card 1. Fixed-tilt panels, no trackers, no reactive power, no wind.
- **One fault type, and a simplified availability**: only an inverter trip is simulated. Availability is time-based over 24
  hours, counts only reasons flagged as counting against it, and ignores daylight and partial losses (ADR 0021).
- **No durable queue for tickets and escalations**: retries and pending escalations wait in the gateway's memory, so a long
  outage or a gateway restart can lose one (ADR 0018, ADR 0019).
- **Manual steps**: the license token, the `API_RW` security level, the write permission, and the API key. Everything else was
  rebuilt from an empty gateway by the tools (finding 51).
- **Tests prove the code, not the gateways**: the unit tests use fake gateways, so they cannot say what a real gateway answers.
  A fake with the wrong shape once passed all its tests while the real answer differed. The status command and the factory
  acceptance test plan check the real gateways, and they run against a simulated plant, so they say nothing about real equipment.

## Repo layout

```
sim/                 the plant simulator: physics, Modbus server, OPC UA plant controller, fault injection, Dockerfile
generator/           points-list generator and the REST and SQL tooling (apply, connections, import_types, providers, deploy_project, sqlfiles, ...)
points/              the points lists (one row per device); the source of truth for devices and instances
projects/            the Perspective projects (views, the alarm pipeline and the Event Stream as files): core, site, fleet
cmms/                the mock maintenance system (FastAPI, SQLite) the Event Stream posts tickets to, with its Dockerfile
sql/                 numbered SQL files: notifications, downtime reasons and view, sites, site KPIs
gateway/             exported gateway state kept for reference (UDT definitions)
docs/layer-cards/    one card per layer: why it exists, what it owns, how it talks to its neighbors
docs/adr/            architecture decision records
docs/spikes/         what each time-boxed experiment found
docs/domain/         a solar plant primer, a battery primer, and a glossary
docs/commissioning/  the factory acceptance test plan and its measured results
.github/workflows/   CI: the test suites on every push, and a gitleaks scan of the whole history
.gitleaks.toml       gitleaks settings: its default rules plus two for Ignition's token shapes
scripts/             check_secrets.py, the pre-commit secret check
spikes/              throwaway experiment files (reference only)
docker-compose.yml   hub, site1, site2, PostgreSQL, cmms, two plant simulators, and six OEM simulators
CLAUDE.md            the working rules for the AI coding agent used on this project
```

## Docs

- [Layer Card 0: platform skeleton](docs/layer-cards/00-platform-skeleton.md)
- [Layer Card 1: field devices and the simulator](docs/layer-cards/01-field-devices-and-simulator.md)
- [Layer Card 2: site views](docs/layer-cards/02-site-views.md)
- [Layer Card 3: fleet and templating](docs/layer-cards/03-fleet-and-templating.md)
- [Layer Card 4: the operations layer](docs/layer-cards/04-operations-layer.md)
- [ADR index](docs/adr/README.md)
- [Factory acceptance test plan and its first results](docs/commissioning/01-fat-plan.md)
- Findings from the experiments: [Phase 0](docs/spikes/phase0-findings.md), [Phase 1](docs/spikes/phase1-findings.md), [Phases 2 and 3](docs/spikes/phase2-findings.md)
- [Solar plant primer](docs/domain/01-solar-plant-primer.md), [battery primer](docs/domain/02-battery-primer.md), [glossary](docs/domain/glossary.md)

## License

[MIT](LICENSE). The licenses of the dependencies and of Ignition itself are separate.
