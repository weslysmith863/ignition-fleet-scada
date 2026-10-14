# ADR 0017: Fault injection by a plant controller node

Status: Accepted (2026-10-12) as the first piece of Phase 3's fault scenarios. Wes chose buttons he triggers himself over a YAML
timeline, and approved starting with one fault, the inverter trip. Wes approved its decisions on 2026-10-14 from a one-line summary of each; he has not read the full text.

## Context

Phase 3's gate is "fault scenarios run end to end": a fault in the plant raises an alarm that reaches a ticket and a downtime
row. The plan assumed YAML scenario files played by the simulator. Wes preferred to be in control of when a fault happens, for
demonstration, and to keep the end-to-end data flow honest: the alarm must come from data that really travelled from the
simulator through Modbus, not from a switch on a gateway tag.

## Decision

1. **The fault is ordered through a new plant controller node and happens inside the simulator.** The plant controller (the EMS
   role, ADR 0010) gets one more writable OPC UA node, `TripInverter` (Int32). `0` means no fault; `1` to the inverter count
   faults that inverter. The plant model then stops that inverter: its DC and AC power are zero, and the plant limit is shared
   out among the inverters still running. This is the same split as the battery: the order goes over OPC UA, the result comes
   back over Modbus.
2. **The result is the inverter's own status.** The inverter's SunSpec model 103 `St` register reads 7 (Fault) while it is
   tripped, even at night, and `W` and `DCW` read 0. The Inverter UDT already maps 7 to "Fault" (it was written from the model's
   published enumeration), so an alarm on the `State` member sees a real change that came through the Modbus read path.
3. **One tripped inverter at a time.** A single number, not a list or one node per inverter, so the UDT needs one new member
   (`TripInverter` in the PlantController type) and no member dangles on a plant with fewer inverters. Tripping a second inverter
   replaces the first. Extending to several at once is a later, separate decision.
4. **Invalid values are ignored and the accepted value is written back,** as for the limit and the battery: a value that is not a
   whole number from 0 to the inverter count leaves the current trip as it was.
5. **Where it exists.** The node is on every simulator that serves the OPC UA plant controller, which is Site 1's and Site 2's.
   The six OEM-integrated sites have no plant controller (ADR 0015), so they cannot be faulted this way and stay read-only. Their
   "comms loss" is shown by stopping the container.
6. **No event code.** `Evt1` stays 0 while an inverter is tripped: a real inverter would also set an event bit, and which bit is
   not modeled here (approximated).

## Consequences

- The `PlantController` UDT needs a new member `TripInverter` (OPC UA, Integer), added by hand on Site 1, exported, and carried to
  Site 2 with `import_types --replace PlantController` (a changed definition does not reach another gateway by itself, finding 70).
- The node's type is a 32-bit integer. A client must write that type: the OPC UA library refuses a 64-bit integer as a type mismatch.
  Ignition's Integer tag type is 32-bit.
- Tests: the simulator now has 156 tests (14 for this). The node count of an untouched controller is seven, nine with a battery.
- Faults other than the inverter trip (underperformance, comms loss, curtailment events, battery faults) are not built. Each gets
  its own decision when it is added.
