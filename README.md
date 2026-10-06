# Fleet SCADA on Ignition 8.3: Solar + BESS Fleet Platform

> **Personal learning project built on Ignition Maker Edition (non-commercial).**
> Not a product, not a customer deployment. Every device and site is simulated, and the numbers are illustrative.
> Ignition is a trademark of Inductive Automation. This project is not affiliated with or endorsed by Inductive Automation.

A SCADA platform for simulated utility-scale solar and battery storage (BESS) sites, built on Inductive Automation's
Ignition 8.3 and designed the way an integrator would: sites generated from templates and a points list, Python and SQL
underneath, and everything stored as files in Git and deployed through the gateway's REST API. It runs from Docker Compose.

## Status

**Phase 1 of 4 (one site end to end) is built and working.** One simulated 5 MW solar plant runs end to end: a Python
simulator, Ignition tags and templates, history in PostgreSQL, and browser screens.

| Phase | Goal | State |
|---|---|---|
| 0 | Spikes and skeleton: hub reads a tag from a site gateway | Done |
| 1 | One site end to end | **Done** |
| 2 | Fleet and templating: 8 sites from one points list, a battery model | Planned |
| 3 | Operations layer: alarms, downtime, Event Streams, fault scenarios | Planned |
| 4 | Admin tooling, CI, commissioning docs, showcase | Planned |

## What works today

- **Simulator** (`sim/`, Python 3): sun position, seeded clouds, module temperature, inverter clipping, a plant-level power
  limit, and a revenue meter. It serves SunSpec Modbus TCP for four inverters, a weather station, and a meter (port 15020), and
  an OPC UA plant controller (port 14840), from one process and one clock. Runs as the `sim` container.
- **Ignition tag model**: four UDT templates (Inverter, Weather, Meter, PlantController), with Modbus scale factors handled by
  expressions and the OPC UA values arriving in engineering units.
- **Points-list generator** (`generator/`, standard library only): reads `points/site1.csv` and creates the Modbus devices, the
  OPC UA plant-controller connection, and the UDT instances through the REST API. It never overwrites, reports drift, and
  creates devices and connections before instances. It also imports the saved UDT definitions, creates the PostgreSQL
  connection (encrypted password) and the SQL Historian provider, deploys projects, and retargets device hosts.
- **History**: SQL Historian on PostgreSQL, with sampling choices recorded in an ADR.
- **Screens** (`projects/site/`): Overview, Trends (a chart that reads the historian), and a Controller page that writes the
  plant limit and shows curtailment. They are Perspective project files deployed with one command.
- **Documentation**: 14 architecture decision records, four layer cards, a domain primer, and findings logs of what the
  experiments showed, including the mistakes.
- **Tests**: 242 automated tests (97 simulator, 145 generator and tooling), standard library only.

## What it demonstrates

Hub and site gateway architecture, UDT and template-driven tag models, Modbus TCP and OPC UA connectivity against a realistic
simulator, solar domain concepts (clipping versus curtailment, plane-of-array irradiance, point of interconnection), SQL
historian, secrets kept out of Git, Git-native project files, and gateway administration through the REST API.

## Quick start

You need Docker Desktop, Python 3, and an [Ignition Maker Edition](https://inductiveautomation.com/ignition/maker-edition)
account with licenses for the gateways (one key and one activation token each).

```
copy .env.example .env        # then fill in the values; .env is gitignored and never committed
docker compose up -d --build  # hub, site1, postgres, and the sim container
```

Then there is first-time setup on a fresh gateway. Only the first step is manual; each of the others is a tool that reports
before it changes anything. They have each been tested, but not yet run in sequence on an empty gateway:

1. In each gateway's web page, create a security level `API_RW`, allow it under *Gateway Write Permissions*, and create an API
   key that holds it. Put the tokens in `.env` (`HUB_API_TOKEN`, `SITE1_API_TOKEN`). See `docs/adr/0005`.
2. `python -m generator.connections site1` creates the PostgreSQL connection `fleetdb` with an encrypted password, then the SQL
   Historian provider `Historian` on it (add `--dry-run` to only report).
3. `python -m generator.import_types site1 --apply` creates the four UDT definitions from `gateway/site1/udt-types.json`
   (without `--apply` it only reports).
4. `python -m generator.apply points/site1.csv` creates the Modbus devices, the OPC UA connection `PlantController` (to
   `opc.tcp://sim:14840/fleet-scada/sim`, security None), and the Inverter, Weather, Meter, and PlantController instances.
5. `python -m generator.deploy_project site1 projects/site` deploys the screens, then open
   `http://localhost:8091/data/perspective/client/site`.

`SIM_START` in `.env` pins the simulated start time (for example midday, so the plant is producing); empty means the real clock.

Run the tests with `python -m unittest discover -s sim/tests -t .` and `python -m unittest discover -s generator/tests -t .`.
The simulator's OPC UA tests need `asyncua` (`sim/requirements.txt`) and are skipped without it.

## Known limits and dev-only choices

These are deliberate for a local, single-machine project, and each is written down so it is not mistaken for a design.

- **No security on local links**: plaintext Gateway Network and API key transport (ADR 0004), an OPC UA server with no security
  (ADR 0010), and Perspective screens with no login that can write the plant limit (ADR 0012). The generator also gives a new
  OPC UA connection the default password for the gateway's own OPC client key store (`password`, Phase 2 finding 45), a dev
  default for a self-generated certificate. All ports are bound to the loopback interface. None of this is suitable for a
  shared deployment.
- **Simulated data**: the code labels what is modeled, approximated, or not modeled (Layer Card 1). Fixed-tilt panels, no
  trackers, no reactive power, no wind.
- **Not run end to end yet**: the setup steps above are each tested, but a rebuild of an empty gateway through all of them has
  not been done. The security level and API key stay manual.
- **One site**. The fleet, the hub's fleet views, alarms, and the battery are later phases.

## Repo layout

```
sim/                 the plant simulator: physics, Modbus server, OPC UA plant controller, Dockerfile
generator/           points-list generator and the REST API tooling (apply, connections, import_types, providers, deploy_project, retarget)
points/              the points list (one row per device); the source of truth for devices and instances
projects/site/       the Perspective project (views as files), deployed through the API
gateway/             exported gateway state kept for reference (UDT definitions)
docs/layer-cards/    one card per layer: why it exists, what it owns, how it talks to its neighbors
docs/adr/            architecture decision records
docs/spikes/         what each time-boxed experiment found
docs/domain/         a solar plant primer and glossary
spikes/phase0/       a throwaway sample project exported from a gateway (reference only)
docker-compose.yml   hub gateway, site1 gateway, PostgreSQL, and the simulator
CLAUDE.md            the working rules for the AI coding agent used on this project
```

## Docs

- [Layer Card 0: platform skeleton](docs/layer-cards/00-platform-skeleton.md)
- [Layer Card 1: field devices and the simulator](docs/layer-cards/01-field-devices-and-simulator.md)
- [Layer Card 2: Site 1 views](docs/layer-cards/02-site-views.md)
- [ADR index](docs/adr/README.md)
- [Findings from the experiments](docs/spikes/phase1-findings.md)
- [Solar plant primer](docs/domain/01-solar-plant-primer.md)

## License

[MIT](LICENSE). The licenses of the dependencies and of Ignition itself are separate.
