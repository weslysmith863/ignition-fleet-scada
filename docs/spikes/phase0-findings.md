# Phase 0 findings

Date: 2026-10-02. Platform: Ignition 8.3.9 Maker Edition in Docker (Java 17), PostgreSQL 16, Windows 11 host.
A spike is a short, time-boxed experiment that answers one technical question before the design depends on it.
The throwaway project from these spikes is kept in `spikes/phase0/hello-spike` as a reference sample of what
Ignition 8.3 writes to disk.

| # | Question | Answer | Where it matters |
|---|---|---|---|
| 1 | Can 8.3.9 run in Docker with Maker licensing? | Yes. The **edition is fixed at first boot** (`IGNITION_EDITION`); a gateway commissioned as `standard` rejects a Maker license ("edition=STANDARD but the license is valid only for edition=MAKER"). Maker uses a per-gateway 8-character key plus an activation token, passed as environment variables. | `docker-compose.yml`, `.env.example` |
| 2 | Does gateway state survive container recreation? | Yes, on named volumes. After a volume wipe (`down -v`), the leased license stays held and the new container gets `code=4 License in use`; regenerate that license's token in the account portal. | Layer Card 0 |
| 3 | Can a site gateway connect to the hub over the Gateway Network? | Yes, provisioned entirely by `GATEWAY_NETWORK_*` variables; the hub restricts who may connect with the `SpecifiedList` policy. The SSL link failed because the site does not trust the hub's self-signed certificate, so local dev uses plaintext. | ADR 0004 |
| 4 | Scripting runtime? | Jython 2.7.4 (Python 2 syntax) inside Ignition; repo tooling is Python 3. | Teach-back topic |
| 5 | How is data stored in 8.3? | Plain files. A project is a folder with `project.json` plus one folder per resource. Tags live on the gateway, not in projects, at `config/resources/core/ignition/tag-definition/<provider>/tags.json`. `resource.json` carries a modification signature and timestamp that change on every save. A few resources (for example `global-props/data.bin`) are binary. | ADR 0005 |
| 6 | Can the repo folder be bind-mounted into a gateway? | It loads at startup, but on a brand-new volume Docker creates `projects/` as root and the gateway faults with AccessDenied, and edits made on the Windows side are not noticed by the running gateway until a scan is requested. Not used as the deploy mechanism. | ADR 0005 |
| 7 | Can the REST API do what the generator needs? | Yes. A key needs a custom security level, and Platform > Security > General Settings > Gateway Write Permissions must allow it (built-in roles cannot be assigned to API keys). The OpenAPI spec is served at `/openapi.json`. Tested: project zip import and export, tag import and export, resource creation, secret encryption, project and config scan. | ADR 0005 |
| 8 | Can secrets stay out of Git? | Yes. `POST /encryption/encrypt` turns a plain value into an embedded secret at deploy time; the Postgres password was applied this way. A file-based secret provider is also available. | ADR 0005 |
| 9 | Which historians work under Maker? | Both. The SQL Historian (provider on PostgreSQL) and the Core Historian each returned about 600 rows for a once-a-second tag over 10 minutes. | Phase 3 design |
| 10 | Do Event Streams work under Maker? | Yes. A Tag Event source feeding a Database handler wrote rows into PostgreSQL, through store-and-forward. The stream is stored as readable `config.json`. HTTP handler still to test in Phase 3. | Phase 3 design |
| 11 | Is DNP3 usable? | No. DNP3 is not offered as a device type on the Maker gateway. The stretch item is dropped. `ModbusTcp` is available. | ADR 0001 stretch list |
| 12 | Which modules ship in the image? | Event Streams, Historian, SQL Historian, SQL Bridge, Web Dev, Modbus v2, OPC UA, Perspective, Reporting, Alarm Notification, Kafka, and a PostgreSQL JDBC driver, among others. | None |

## Environment quirks on this PC

- The shell used by the assistant predates the Docker install, and a stray empty file
  `C:\Windows\System32\docker` shadows the `docker` command in PowerShell. Call `docker.exe` by its full path.
- Docker Desktop must be running for the gateways to run. Containers set to `unless-stopped` come back by themselves
  when Docker starts.
