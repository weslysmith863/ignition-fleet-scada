# ADR 0007: Phase 1 tag layout, Inverter UDT shape, historian, alarms, and plant controller nodes

Status: Accepted (2026-10-03).

## Context

ADR 0006 fixed the plant, the register map, the addressing, and the simulator's runtime. Five more choices shape the
tag tree, the Inverter UDT, and the points-list columns before any of them are built. Domain background is in
[the solar plant primer](../domain/01-solar-plant-primer.md).

## Decision

1. **Tag layout.** Every site gateway uses the `default` tag provider, with no site name inside the tree. Top-level
   folders are `Inverters/Inv1` to `Inv4`, `Weather`, `Meter`, and `PlantController`. Site identity comes from the
   gateway and from the name of the hub's remote tag provider (`Site1`, `Site2`, and so on), not from folder names.
2. **Inverter UDT.** Parameters: `Device` (the Modbus device name), `UnitId`, and `RatedKW`. Two layers of members: a
   `Raw` folder of OPC tags exactly as read from the registers (SunSpec point names such as `W` and `W_SF`), and
   engineering-unit members that views and history use (such as `ACPower_kW`), computed by expression from the raw
   tags and their scale factors. The exact member list is set when the points list is written.
3. **Historian.** The SQL Historian on PostgreSQL for Site 1. Both historians worked in Phase 0; the Core Historian
   is revisited in Phase 3 as a documented trade-off. No storage or query-speed comparison has been made.
4. **Alarms.** The alarm priority scheme is deferred to Phase 3. In Phase 1 the Inverter UDT carries only the state
   and event members that alarms will need.
5. **Plant controller (OPC UA).** The simulator's OPC UA server exposes five nodes: `ActivePowerLimit_MW` (write),
   `LimitEnable` (write), `LimitActive` (read), `POI_MW` (read), and `Status` (read). The simulator enforces an
   accepted limit by capping inverter output, so curtailment appears in the data. Reactive power is not modeled: the
   plant runs at unity power factor, and the simulator's documentation labels that as approximated.

## Consequences

- Shared projects (`core`, `site`) reference relative tag paths, so every site must have the same tree. The generator
  must emit this layout for every site.
- At the hub, a site's tags appear under its remote provider, for example `[Site1]Inverters/Inv1/...`.
- The scaling expression was proven in a plain folder (finding 13), not inside a UDT. Expecting it to work inside a
  UDT is untested; the hand-built Inverter UDT is the first test.
- The plant controller is the first OPC UA client connection, a different resource type (`ignition/opc-connection`)
  from the Modbus devices. It appears in the REST API's resource list and has not been exercised yet.
- Weather and Meter members are not decided here.
