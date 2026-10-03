# ADR 0006: Phase 1 plant size, register map, addressing, and simulator clock

Status: Accepted (2026-10-03). The scale-factor spike passed (see Consequences).

## Context

Phase 1 builds one site end to end. Four choices fix the shape of the simulator, the Inverter UDT, and the points
list, so they are settled before any of those exist. Domain background is in
[the solar plant primer](../domain/01-solar-plant-primer.md).

## Decision

1. **Site 1 plant.** Four inverters of 1.25 MWac each (5 MWac) with an inverter loading ratio of 1.34, about
   6.7 MWdc of modules. These are the primer's worked-example numbers. They are illustrative, not a real plant.
2. **Register map.** A subset of SunSpec model 103 (three-phase inverter), keeping its scale factors, plus the
   active-power-limit points of model 123 (`WMaxLimPct`, `WMaxLim_Ena`, `WMaxLimPct_RvrtTms`). The definitions come
   from the public SunSpec model files. The exact subset is chosen when the points list is written. Rejected: a
   made-up vendor-style map without scale factors. It is simpler, but it teaches less and cannot be checked against
   a public specification.
3. **Addressing.** One simulator endpoint per site, with Modbus unit IDs 1 to 4 for the four inverters. Ignition
   gets one Modbus TCP device per inverter, all pointing at that endpoint. The unit ID is not a device setting: it
   is part of every tag address (`[Device]3.HR40085`), so the Inverter UDT takes the unit ID as a parameter. Each
   points-list row carries device name, host, port, and unit ID. This approximates real sites, where each inverter
   often has its own IP address, and it gives each inverter its own connection status. (First written on the
   assumption that the unit ID was a device setting; the spike showed it is not, and this was corrected before the
   ADR's first commit.)
4. **Simulator runtime and clock.** Python 3, as a new `sim` service in Docker Compose, reachable from the gateways
   by service name. It runs in real time by default, with a start-time option (for example begin at 10:00). An
   accelerated mode is demo-only.

## Consequences

- **Spike results (2026-10-03, site1, a throwaway Modbus server; see `spikes/phase1/sunspec-scale-factor`).**
  Verified from the server's request log: the unit ID is taken from the tag address, and one device connection
  served units 1 and 2; Ignition's default addressing is one-based, so `HR40085` reads wire address 40084 (SunSpec
  `W`); `W`, `W_SF`, `Hz`, and `Hz_SF` were read as a single batched request per unit. The device REST resource
  rejects a partial settings object (every settings group is needed), so the generator builds device settings from
  the schema defaults. The scaled values were confirmed in Designer through expression tags
  (`{[.]W} * pow(10, {[.]W_SF})`): 42000 W and 123.4 W for the two units, 60 and 59.98 Hz. Details are in
  [phase1-findings.md](../spikes/phase1-findings.md).
- The plant numbers live in the points list and the simulator profile, so changing them later is a CSV edit.
- Accelerated mode is demo-only because gateway timestamps come from the wall clock, not the simulator's clock, so a
  sped-up day would produce strange history. This is reasoning, not a tested result.
- Decisions 1 to 4 do not cover tag naming, UDT parameters, historian choice, alarms, or the OPC UA plant
  controller. Those come in later design batches.
