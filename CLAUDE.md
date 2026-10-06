# CLAUDE.md

Fleet SCADA on Ignition 8.3: a solar + BESS fleet platform, built as a personal learning project on Ignition Maker
Edition (non-commercial). Wes, the owner, is learning the stack while building it. The goal is that he can explain
every layer and direct an agent to rebuild the system.

## Start of session
1. Read the Notion handoff page "Fleet SCADA on Ignition 8.3 - Solar + BESS Fleet Platform (Handoff)"
   (https://app.notion.com/p/3ecc8722b14881edb84cd80d6b4dd28a) and its Teach-back Log subpage. They hold the
   status, decisions, phase plan, and what Wes has and has not yet shown he understands. You are ready when you can
   state the current phase, the next three steps, and the working agreement below in your own words.
2. Run the cold-start checklist (section 10 of that page) before touching gateways. It includes starting the
   simulator, which Wes types (see "Repo map and commands").
3. Check `docs/adr/` (decisions), `docs/layer-cards/` (layer explanations), and `docs/spikes/` (evidence) before
   proposing a design; the question may already be decided.

## Working agreement
- **Teach-back loop.** Write the Layer Card, let Wes hand-build the first instance of each Ignition pattern in
  Designer, then quiz him: 3 to 5 questions in his own words, at least one on architecture and one on the solar
  domain. Log solid, shaky, or redo in the Teach-back Log. The next phase starts when nothing is redo.
- **One step at a time.** Wes performs the Designer, gateway-page, and account-portal steps and reports what he
  sees. Ask for screenshots of unfamiliar screens.
- **Define terms at first use** (inverter, SSL, spike, volume), idea first, then the word.
- **Wes runs the operational commands himself** (`docker compose ps`, `up -d`, `logs`, `stop`) and explains what each
  does; the agent ran them all in Phase 0.
- **Hand-build the new, generate the repeated.** Wes hand-builds the first instance of each pattern (device, UDT
  definition, instance). Once a pattern is understood, the points-list generator makes the repetition. It never
  overwrites or deletes hand-built objects. Exception, decided by Wes on 2026-10-05: Wes has practiced Perspective views
  (DosingControl) and would rather watch what the API can do, so the agent builds the views as project files in the
  repo and deploys them through the REST API. Wes reviews them in a browser and is still quizzed on how a view gets its
  data, how history reaches a chart, and how the project is deployed.
- **Predict, then look.** Before showing live values or output, ask Wes to predict them in his own words; it surfaces
  misunderstandings early.
- **Put settings that matter in the prose,** not only in a table column. A Data Type column was missed once and silently
  broke four tags.
- **Separate verified from guessed.** Run a spike for risky unknowns, label guesses as guesses, and say plainly when
  an earlier claim turned out wrong.
- **Questions come numbered, each with a recommended answer.**
- **Show progress** with short status lines during long work.
- **Ask before** commits, pushes, downloads, deletions, and security-setting changes. Wes changes gateway security
  settings himself.
- **Secrets live in the gitignored `.env`.** Validate their shape and length without printing them. Wes pastes keys
  and tokens into `.env` only, never into chat. `scripts/check_secrets.py` is the pre-commit hook
  (`git config core.hooksPath .githooks`).
- **Stuck for 30 minutes:** walk Wes through the step.
- **End of session:** update Status, Decisions, and the Teach-back Log in Notion, and offer a commit that lists what
  it contains.

## Design objectives
Fleet scale from templates and a points list. Deploy through the REST API (ADR 0005). Reproducible from
`docker compose up`. Honest about what the simulator models. Dev-only relaxations recorded as ADRs. Every layer
explainable.

## Repo map and commands
- `sim/`: the simulator (physics, plant model, SunSpec Modbus server on 15020, OPC UA plant controller on 14840). It runs
  as the `sim` Compose service (ADR 0013): `docker.exe compose up -d --build sim` builds and starts it, and the gateways reach it
  as `sim:15020` and `sim:14840`. `SIM_START` in `.env` (optional, UTC, e.g. `2026-10-05T17:00:00Z`) pins the simulated
  start so the plant is producing; empty means the real clock. Without the simulator the gateways' Modbus devices fault and tags
  read bad. For development it can still run in its own terminal with the project's `.venv` Python (OPC UA needs `asyncua`,
  `sim/requirements.txt`): stop the container first, then
  `.\.venv\Scripts\python.exe -m sim.modbus_server --port 15020 --start <a daytime UTC time> --seed 1`. With plain `python`
  (no `asyncua`) only Modbus runs and the log says OPC UA is off. Port 5020 is not ours (DosingControl).
- `generator/` and `points/site1.csv`: the points list and the generator. `python -m generator.apply points/site1.csv
  [--dry-run]` creates missing devices and instances and reports drift. `python -m generator.export_types site1` saves
  the gateway's UDT definitions to `gateway/site1/udt-types.json`.
- `docs/points/site1-register-map.md` is generated by `python -m sim.register_map --markdown`; do not edit it by hand.
- Tests use only the standard library: `python -m unittest discover -s sim/tests -t .` and the same with
  `-s generator/tests`. Run the first one with `.venv\Scripts\python.exe` to include the 3 OPC UA tests; plain
  `python` skips them.

## Gotchas (the reason behind each)
- UDT definitions live in the gateway's data volume, not in a project. Export them after every edit in Designer
  (`python -m generator.export_types site1`), or a `down -v` loses them.
- The gateway's OPC UA connection `PlantController` (to `opc.tcp://sim:14840/fleet-scada/sim`, security None) and the
  PlantController tag instance live in the gateway volume too, and the generator does not create them yet (ADR 0010).
  Inside a container `127.0.0.1` is the container itself; containers reach each other by service name (`sim`, `postgres`).
  `python -m generator.retarget site1 points/site1.csv [--apply]` moves existing devices and that connection to the host in
  the points list; it changes only host and port.
- A tag that subscribes before its device is healthy can stay on `Bad_NodeIdUnknown` until it is restarted (Restart
  Tag in Designer). The generator creates devices first and waits for them.
- A gateway's edition is fixed at its first boot (`IGNITION_EDITION`); fixing a wrong one means wiping that
  gateway's volume.
- Maker licenses are leased per gateway (key and token in `.env`), and Maker allows 3 active gateways. After
  `docker compose down -v`, regenerate that license's token in the account portal first, or the new container gets
  `code=4 License in use`.
- Projects, tags, and gateway resources deploy through the REST API. Bind-mounting repo folders into a fresh volume
  faults the gateway. An API key needs the custom security level `API_RW` and the gateway setting Gateway Write
  Permissions allowing it.
- Gateway scripts run Jython 2.7 (Python 2 syntax). Repo tooling is Python 3.
- Windows shell: a stray empty `System32\docker` file shadows the bare `docker` command in PowerShell, so it prints
  nothing. Type `docker.exe` (with the extension) instead; that skips the stray file (verified in Wes's terminal on
  2026-10-03). The assistant shell's PATH also predates Docker, so there call
  `%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe` by full path. The command filter misreads `rm` and
  `Remove-Item` text even inside harmless commands, so delete files with Python.
- Port 5020 belongs to the native DosingControl gateway's Modbus device: it connected to a spike server there on
  2026-10-03 (inferred from the process tree; its device settings were not inspected). Use another port for spikes
  (15020 worked).
- Keep this repo outside OneDrive. Keep every file LF (`.gitattributes`).

## Public-repo hygiene
This repository goes public at the end of Phase 1. Personal information and Wes's learning notes belong in the
private Notion pages, never in this repo.
