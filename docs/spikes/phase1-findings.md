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

## Findings from the hand-built Inverter UDT (2026-10-03)

| # | Question | Answer | Where it matters |
|---|---|---|---|
| 21 | Does Ignition's default `HRUI` word order read a SunSpec 32-bit value correctly? | Yes. The `WH` energy counter (high word 9, low word 17326 at the time) read as 598.12 kWh in the tag and 607.15 kWh from the simulator about 26 seconds later, matching the roughly 21 kWh per minute at full output. A swapped word order would have read about 1.1 million kWh. | Register map, Inverter UDT |
| 22 | What are the Data Type names in Designer? | They differ from the JSON names: Short is Int2, Integer is Int4, Long is Int8, Double is Float8. A member left at the default is exported without a `dataType` key, so an expression tag left at Integer is silent in the export and rounds its result. The expression text and value source were saved exactly as typed. | Generator, UDT hand-build instructions |
| 23 | Where can folders and parameters go in a UDT definition? | The UDT Definitions tree holds types, and folders there organize types. Inside a type, folders are allowed as members (the Raw folder). New parameters can only be added at the type's top node. A parameter-bound OPC item path is exported as `bindType: parameter` and shown in italics in the editor. (From the Ignition documentation and observed in the editor.) | Inverter UDT |
| 24 | Does a relative reference into a sub-folder work inside a UDT instance? | Yes. `{[.]Raw/W}` and the other expressions evaluated with good quality on the `Inv1` instance. | ADR 0007 consequence closed |
| 25 | How does the tag export report a path that does not exist? | HTTP 200 with `"tagType": "Unknown"`, not a 404. With `recursive=false` the export returns just the one tag, folder, or UDT instance (name, parameters, type) without its children. A device that does not exist does give a 404. | Generator: existence checks look for `Unknown` |
| 26 | What happens to a tag whose device does not exist yet when it subscribes? | The tags showed `Error_ExpressionEval` (and `State` Unknown), with the message `CreateMonitoredItems failed: Bad_NodeIdUnknown` on the raw members, while the device was healthy and the parameters correct. They stayed that way until **Restart tag** was chosen from the tag's menu in Designer, after which they read normally. Inferred cause: the instance subscribed to `[Inv2]2.HR40085` before the `Inv2` device existed and did not retry. Evidence: device and parameters were correct from the REST side, and a tag restart cleared it. | Generator creates every device before the instances; hand-built order matters too |

## How the spike ran

`server.py` is a standard-library Modbus TCP server for units 1 and 2 with a SunSpec model 103 block at base address
40000 and different scale factors per unit. `setup.py` is the code that created the `SpikeSF` device and tags on
site1 through the REST API, saved as it was run in a scratch session. It reads the API key from the gitignored
`.env`, and it has not been re-run from the repo. The spike's device and tags were removed from site1 afterwards, and
the spike server was stopped.
