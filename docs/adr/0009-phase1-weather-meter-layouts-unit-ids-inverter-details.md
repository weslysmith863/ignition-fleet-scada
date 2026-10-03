# ADR 0009: Weather station and meter layouts, unit IDs, and inverter details

Status: Accepted (2026-10-03).

## Context

ADR 0006 chose SunSpec register layouts for the inverters, and ADR 0008 chose the weather and meter signals. Two things were
still open before the Modbus server could be written: how the weather station and POI meter present their signals, and a few
inverter details. No single SunSpec weather model carries GHI, POA, ambient temperature, and module temperature together:
model 307 has ambient temperature but no irradiance, and model 308 (Mini Met) has GHI but no POA.

## Decision

1. **Weather station (unit 5).** Three published SunSpec models chained in one unit: 302 (irradiance: GHI, POA, and, because
   the plant model computes them anyway, diffuse and direct beam), 303 (back-of-module temperature), and 307 (ambient
   temperature). Unused points, including wind, are served as "not implemented". The model's cell temperature stands in for
   the back-of-module temperature, which is an approximation.
2. **POI meter (unit 6).** SunSpec model 203 (three-phase wye meter). Populated: total power, line-to-neutral and
   line-to-line voltage, frequency, current, and exported energy. Everything else is "not implemented".
3. **Unit IDs.** Inverters 1 to 4, weather station 5, meter 6, all on one simulator endpoint (ADR 0006).
4. **Inverter details.**
   - The model 123 power-limit points are read-only mirrors of the plant limit in Phase 1. Writes are refused, because the
     Phase 1 control path is the OPC UA plant controller (ADR 0007).
   - Operating state: SLEEPING at night, MPPT normally, THROTTLED when the inverter is clipping or limited.
   - AC voltage is an assumed 600 V line-to-line.
   - The `A` point (model 103 describes it only as "AC Current") reports the sum of the phase currents, following model 203's
     wording "Total AC Current".

## Consequences

- Scale factors are chosen so every value fits its 16-bit register. For example an inverter's `W` is a signed 16-bit register
  (maximum 32767), so a 1.25 MW inverter needs `W_SF` = 2 (units of 100 W).
- Unimplemented points use SunSpec's published not-implemented values: 0x8000 for signed 16-bit points and scale factors,
  0xFFFF for unsigned 16-bit points, 0 for accumulators. These were read from a search excerpt of the SunSpec specification,
  not the specification text itself.
- Register positions for every populated point are checked against the public SunSpec model files by a test that runs when the
  network is available.
- Reading a model 123 point is possible; writing one returns a Modbus "illegal function" exception until Phase 3 needs
  inverter-level limits.
- The meter reports exported energy only; imported energy stays at zero.
