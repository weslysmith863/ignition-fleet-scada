# ADR 0008: Phase 1 simulated site, panel orientation, clouds, and weather and meter signals

Status: Accepted (2026-10-03).

## Context

ADR 0006 and 0007 settled the plant, the register map, the tag layout, and the plant controller. Four more choices decide
what physics the simulator contains and which weather and meter signals exist. The physics chain and its sources are in
[Layer Card 1](../layer-cards/01-field-devices-and-simulator.md).

## Decision

1. **Location and clock.** An illustrative west-Texas location, about 31.0°N, 102.0°W, in the Central time zone that
   Compose already uses. No real plant is implied. The date and clock follow the real wall clock. Sun position comes
   from the NOAA solar position equations, evaluated on the UTC clock so daylight saving never enters.
2. **Panel orientation.** Fixed tilt facing south, with a tilt near the latitude. This is a labeled approximation: tracker
   mechanics are out of scope, and real utility-scale plants commonly use single-axis trackers.
3. **Clouds.** A seeded random factor dims the clear-sky irradiance, with a fixed default seed so runs are repeatable.
   Fault scenarios in YAML come later (decision D12).
4. **Phase 1 signals.** Weather station: GHI, POA, ambient temperature, and module temperature (no wind, because the model
   does not use it). POI meter: MW, MWh, and voltage.

## Consequences

- Latitude and longitude fix sunrise, sunset, and how high the sun climbs; changing the site later is a configuration
  change, not a code change.
- Module temperature is included because panel output falls as panels heat up.
- Modbus unit IDs for the weather station and the meter are still open; they are set when the points list is written.
- Cloud behavior is a design choice with no published basis, and the simulator's documentation says so.
