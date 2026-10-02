# Fleet SCADA on Ignition 8.3: Solar + BESS Fleet Platform

> **Personal learning project built on Ignition Maker Edition (non-commercial).**
> Not a product, not a customer deployment. All devices and sites are simulated.

A fleet-scale SCADA platform for simulated utility-scale solar + battery storage (BESS) sites, built on
Inductive Automation's Ignition 8.3 and designed the way an integrator would: many sites generated from
templates and a points list, a hub gateway for the fleet view, Python and SQL underneath, and the data
feeding enterprise systems. Everything is Git-native (Ignition 8.3 stores config and projects as JSON files)
and runs from Docker Compose.

**Status:** Phase 0 (spikes and skeleton). See the phase plan below.

## What it demonstrates

- Hub + site gateway architecture over the Gateway Network, with store-and-forward
- UDT / template-driven tag model generated from a points-list CSV
- Modbus TCP and OPC UA field connectivity against a realistic Python simulator with scripted fault scenarios
- Alarm strategy (priority pipelines, shelving), downtime reason codes
- Event Streams integrations to a mock CMMS and SQL; historian with scheduled export to S3-compatible storage
- Gateway administration automation through the Ignition 8.3 REST API
- CI for a SCADA repo; commissioning documentation (points list, FAT plan, runbook)

## Phases

| Phase | Goal |
|---|---|
| 0 | Spikes and skeleton: hub reads one tag from a site gateway |
| 1 | One site end to end |
| 2 | Fleet and templating: 8 sites from one CSV |
| 3 | Operations layer: alarms, downtime, Event Streams, export, fault scenarios |
| 4 | Admin tooling, CI, commissioning docs, showcase |

## Repo layout (planned)

```
docs/layer-cards/   one card per layer: why it exists, what it owns, how it talks to its neighbors
docs/adr/           architecture decision records
docs/spikes/        what each time-boxed experiment found
spikes/phase0/      throwaway sample project exported from a gateway (reference only)
docker-compose.yml  the stack: hub gateway, site1 gateway, PostgreSQL
.env.example        copy to .env (gitignored) and fill in
```

## Quick start

Filled in at the end of Phase 0.

## Docs

- [Layer Card 0: platform skeleton](docs/layer-cards/00-platform-skeleton.md)
- [ADR index](docs/adr/README.md)
