# CLAUDE.md

Fleet SCADA on Ignition 8.3: a solar + BESS fleet platform, built as a personal learning project on Ignition Maker
Edition (non-commercial). Wes, the owner, is learning the stack while building it. The goal is that he can explain
every layer and direct an agent to rebuild the system.

## Start of session
1. Read the Notion handoff page "Fleet SCADA on Ignition 8.3 - Solar + BESS Fleet Platform (Handoff)"
   (https://app.notion.com/p/3ecc8722b14881edb84cd80d6b4dd28a) and its Teach-back Log subpage. They hold the
   status, decisions, phase plan, and what Wes has and has not yet shown he understands. You are ready when you can
   state the current phase, the next three steps, and the working agreement below in your own words.
2. Run the cold-start checklist (section 10 of that page) before touching gateways.
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

## Gotchas (the reason behind each)
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
- Keep this repo outside OneDrive. Keep every file LF (`.gitattributes`).

## Public-repo hygiene
This repository goes public at the end of Phase 1. Personal information and Wes's learning notes belong in the
private Notion pages, never in this repo.
