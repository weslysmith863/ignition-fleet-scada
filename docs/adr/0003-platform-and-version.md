# ADR 0003: Platform, version pin, and what goes in Git

Status: Accepted, details pending Phase 0 spikes

## Context

Ignition 8.3 stores gateway configuration and projects as JSON files on disk instead of an internal database,
which makes Git-based workflows possible. It also adds Event Streams, a built-in REST API (OpenAPI), secrets
management, and a redesigned gateway. Docker images are published per release.

## Decision

- Pin `inductiveautomation/ignition:8.3.9` (latest stable tag on 2026-10-01; 8.3.10 is still release-candidate).
  Matches the 8.3.9 install already on the author's PC.
- Run every gateway as a Docker Compose service with its data directory on a persistent volume.
- Track Ignition projects and gateway configuration resources in Git as JSON.
- Do not track runtime artifacts. Whether the `.resources/` folder can be ignored is **to be confirmed in the
  Phase 0 spike** (community guidance says it need not be committed).
- The mechanism by which the generator applies tags and UDTs to a gateway (write JSON files vs REST config API vs
  import) is **decided at the end of Phase 0** and recorded as a new ADR.

## Open questions for Phase 0

1. How does Maker activation work inside containers, and does it survive container recreation?
2. Can the Gateway Network link be established, and approved, without manual UI steps?
3. Are the Core Historian, the DNP3 driver, and the Event Streams Database and HTTP handlers available under Maker?
4. Which scripting runtime does 8.3.9 use (expected: Jython 2.7)?
