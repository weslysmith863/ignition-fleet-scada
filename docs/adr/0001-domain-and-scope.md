# ADR 0001: Domain and scope

Status: Accepted (2026-10-01)

## Context

The target roles ask for Ignition at fleet scale: template-driven tag models, multiple gateways, Python and SQL,
historian and enterprise integration, alarm strategy, and Git/CI. The highest-paid, most remote-friendly roles
are in utility-scale solar and battery storage (BESS). The author's field background is water treatment, so the
domain needs a primer and honest labeling of what is simulated.

## Decision

- Domain: utility-scale solar PV plus BESS sites, fully simulated.
- Core scope: UDT model and points-list-driven generator; Perspective views; alarm strategy and downtime codes;
  Event Streams integrations; historian with S3-compatible export; REST-API admin tooling; Git-native repo and CI;
  commissioning documents; simulator with scripted fault scenarios.
- Stretch: MQTT/Sparkplug path, DNP3 outstation emulation, legacy points-list normalization tool, audit trail.
- Out of scope: MES (Kanoa, Sepasoft), real RTAC hardware, IEC 61850, ICCP, Vision.
- Every simulator assumption is labeled "modeled" or "approximated".

## Consequences

Oil and gas and MES roles are covered only through shared skills (multi-gateway admin, Python, SQL, protocols).
Perspective is the only UI technology.
