# Phase 1 findings

Date: 2026-10-03. Platform: Ignition 8.3.9 Maker Edition in Docker (site1 gateway), Windows 11 host. Numbering
continues from [phase0-findings.md](phase0-findings.md). The spike code is in
`spikes/phase1/sunspec-scale-factor/`.

| # | Question | Answer | Where it matters |
|---|---|---|---|
| 13 | Can Ignition's Modbus TCP driver read SunSpec registers with scale factors, from more than one unit ID? | Yes. The unit ID is part of the tag address (`[Device]1.HR40085`), not a device setting, and one device connection served units 1 and 2. Ignition's default addressing is one-based, so `HR40085` goes on the wire as address 40084, where SunSpec model 103 puts `W`. `W`, `W_SF`, `Hz`, and `Hz_SF` were read as one batched request per unit. An expression tag `{[.]W} * pow(10, {[.]W_SF})` produced 42000 W and 123.4 W for the two units, and 60 and 59.98 Hz from `Hz` and `Hz_SF`; quality was good (values read in Designer). `HR` is a signed 16-bit register and `HRUS` an unsigned one. | ADR 0006, Inverter UDT |
| 14 | Does the device REST resource accept a partial settings object? | No. Sending only `connectivity` returned HTTP 500 (a NullPointerException on `requestOptimization`). All six settings groups are needed (`connectivity`, `requestOptimization`, `writeRequests`, `readRequests`, `advanced`, `stringHandling`). The schema defaults are served by `GET /data/api/v1/resources/type/com.inductiveautomation.opcua/device`. | Generator |
| 15 | Can a gateway container reach a server that listens only on the PC's loopback address? | Yes, through `host.docker.internal` (Docker Desktop on Windows). | Spikes only; the simulator will be a Compose service |
| 16 | Is port 5020 free on this PC? | No. The native Windows gateway (`IgnitionGateway.exe`, DosingControl, port 8088) connected to a spike server there within seconds and read unit 1, address 0, 32 registers, once a second. Inferred from the process tree; that gateway's device settings were not inspected. Spikes should use another port (15020 worked). | CLAUDE.md gotchas |
| 17 | Can tag values be read through the REST API? | No endpoint found in the 461-path spec: tag calls are limited to export and import (plus provider calls), which carry definitions, not values. Values were checked in Designer. | Admin tool design (Phase 4) |
| 18 | Is the OpenAPI spec public? | No. `GET /openapi.json` returns 403 without an API key and 200 with one. A key is also per gateway: the hub's key is rejected by site1. | Generator, CI |
| 19 | Can Designer show tags without a project? | Not in this run: a project had to be created first (reported while checking the spike tags). | Phase 1 Designer steps |
| 20 | Can the REST API remove tags? | No delete endpoint found in the spec. Tag import accepts the collision policies Abort, Overwrite, Rename, Ignore, and MergeOverwrite, so tags can be created, replaced, or merged but not removed. The spike tags were deleted in Designer; the spike device was deleted through the REST API (`POST /resources/delete/...` with name and signature). | Generator (retiring a point) |

## How the spike ran

`server.py` is a standard-library Modbus TCP server for units 1 and 2 with a SunSpec model 103 block at base address
40000 and different scale factors per unit. `setup.py` is the code that created the `SpikeSF` device and tags on
site1 through the REST API, saved as it was run in a scratch session. It reads the API key from the gitignored
`.env`, and it has not been re-run from the repo. The spike's device and tags were removed from site1 afterwards, and
the spike server was stopped.
