# Architecture Decision Records

One short file per decision: context, decision, consequences. Numbered, never rewritten. If a decision
changes, add a new ADR that supersedes the old one.

| # | Title | Status |
|---|---|---|
| [0001](0001-domain-and-scope.md) | Domain and scope | Accepted |
| [0002](0002-topology-and-maker-cap.md) | Topology under the Maker activation cap | Accepted |
| [0003](0003-platform-and-version.md) | Platform, version pin, and what goes in Git | Accepted, details pending Phase 0 |
| [0004](0004-dev-gateway-network-plaintext.md) | Plaintext Gateway Network for local development | Accepted (dev only) |
| [0005](0005-deploy-and-configure-via-rest-api.md) | Deploy and configure gateways through the REST API | Accepted |
| [0006](0006-phase1-plant-register-map-and-simulator.md) | Phase 1 plant size, register map, addressing, and simulator clock | Accepted |
| [0007](0007-phase1-tag-layout-udt-historian-alarms-plant-controller.md) | Phase 1 tag layout, Inverter UDT shape, historian, alarms, and plant controller nodes | Accepted |
| [0008](0008-phase1-simulated-site-orientation-clouds-signals.md) | Phase 1 simulated site, panel orientation, clouds, and weather and meter signals | Accepted |
| [0009](0009-phase1-weather-meter-layouts-unit-ids-inverter-details.md) | Weather station and meter layouts, unit IDs, and inverter details | Accepted |
| [0010](0010-phase1-opcua-plant-controller-server.md) | OPC UA plant controller server in the simulator | Accepted (security off, dev only) |
| [0011](0011-phase1-historian-database-connection-and-sampling.md) | Phase 1 database connection, SQL Historian, and history sampling | Accepted |
| [0012](0012-phase1-site-views-as-project-files.md) | Site 1 views are project files in the repo, deployed through the REST API | Accepted (no login, dev only) |
| [0013](0013-phase1-simulator-as-a-container.md) | The simulator runs as a Compose service named sim | Accepted |
