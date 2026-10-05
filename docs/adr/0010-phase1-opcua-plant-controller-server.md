# ADR 0010: OPC UA plant controller server in the simulator

Status: Accepted (2026-10-05). The no-security setting is for development only; revisit before any shared or demo deployment.

## Context

ADR 0007 decision 5 gave the plant controller five OPC UA nodes. This ADR records how the simulator serves them. The
library is `asyncua` 2.0.1 (pure Python, from PyPI), pinned in `sim/requirements.txt` and installed in a gitignored `.venv`.

## Decision

1. **Behavior is separate from the protocol.** `sim/plant_controller.py` (standard library only, unit-tested) decides what
   the five nodes say and how a written limit reaches the plant model. `sim/opcua_server.py` only publishes and relays.
2. **Same process as the Modbus server.** `python -m sim.modbus_server` starts both, so the Modbus registers, the weather
   and meter readings, and the OPC UA nodes all come from one plant model and one clock. OPC UA is on port 14840 by
   default (`--opcua-port`, 0 turns it off). Without `asyncua` the Modbus server runs alone and logs that OPC UA is off.
3. **Nodes.** An object `PlantController` in the namespace `urn:fleet-scada:simulator` (index 2 in a fresh server), with text
   node IDs such as `ns=2;s=PlantController.POI_MW`. Endpoint: `opc.tcp://<host>:14840/fleet-scada/sim`.
   - `ActivePowerLimit_MW` (Double, write) and `LimitEnable` (Boolean, write). The limit starts at the plant rating (5 MW)
     and is disabled.
   - `LimitActive` (Boolean, read): true only while the limit is actually reducing output. An enabled limit above what the
     plant could produce anyway reads false. This is what separates curtailment from clipping.
   - `POI_MW` (Double, read): the plant output at the point of interconnection.
   - `Status` (String, read): `Curtailed` while a limit is active, `Producing` while there is output, `Standby` otherwise.
     The three words are a design choice, not taken from a standard.
4. **Accepted values are written back.** A limit is held between 0 and the plant rating, and a value that is not a finite
   number is ignored. The server writes the accepted limit back into the node, so a client that wrote 99 sees 5.
5. **Writes are polled** twice a second instead of using a write callback. A limit lands within half a second, then takes
   effect on the plant model's next one-second step. Simpler, and inside the model's own time resolution.

## Dev-only relaxation

The OPC UA server accepts anonymous clients with no signing or encryption (`SecurityPolicy None`), the same kind of
local-only shortcut as ADR 0004. A real plant controller would use signed and encrypted sessions with trusted certificates.

## Consequences

- The gateway's first OPC UA connection (a resource of a different type from the Modbus devices) points at this endpoint
  with security policy None. The hostname the server advertises is the one it was started with (`127.0.0.1` by default); if
  the gateway container cannot use it, that is the first thing to check (not yet tested from a gateway).
- Reactive power is still not modeled (unity power factor, approximated; ADR 0007).
- Tests that need a real OPC UA client skip themselves when `asyncua` is missing, so the standard-library test run stays green.
