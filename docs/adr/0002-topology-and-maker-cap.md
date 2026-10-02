# ADR 0002: Topology under the Maker activation cap

Status: Accepted (2026-10-01)

## Context

Ignition Maker Edition is free for non-commercial use but allows 3 concurrently active gateways, with limits of
10,000 tags and 10 Perspective sessions per gateway. A realistic fleet has site-local gateways plus a central
fleet view.

## Decision

- Topology: one hub gateway plus two site gateways (3 activations).
- Fleet: 8 sites generated from one points-list CSV. Two are full site gateways. Six are "OEM-integrated" sites
  that the hub reads directly over OPC UA / Modbus, the way an owner integrates OEM SCADA.
- Roughly 365 tags per site puts the hub near 3,000 tags, well under the 10,000 cap.
- Cut line: if Phase 2 slips, reduce to 5 sites (2 gateway sites plus 3 OEM-integrated).
- Phases 0 and 1 need two activations; the third is needed from Phase 2.

## Consequences

All three activations are consumed during Phase 2 onward, so unused gateways on the same account must be
unactivated first. Gateway data lives on persistent volumes so recreating a container does not burn an activation.
