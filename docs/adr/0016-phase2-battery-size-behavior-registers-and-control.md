# ADR 0016: The battery: size, behavior, registers, and control

Status: Accepted (2026-10-07) as the working details of ADR 0014 decision 8. Wes approved decisions 1 to 6 as recommended in
the design batch on 2026-10-07 and agreed to decision 7 in the same session. Wes has not reviewed the written ADR yet.

## Context

ADR 0014 decision 8 fixed the battery's scope: AC-coupled, state of charge that follows power, a taper near empty and full,
one round-trip efficiency, Idle, Charge, and Discharge modes with a MW setpoint, and a POI meter that reads PV plus battery. It
left the size, the numbers, the register layout, and the control path for after the battery primer (`docs/domain/02-battery-primer.md`).
The values below are design choices unless a source is named; real batteries differ.

## Decision

1. **Where.** Site 1 only for now. `SIM_BATTERY_KW` and `SIM_BATTERY_KWH` (and `--battery-kw`, `--battery-kwh`) give a plant its
   battery; unset or 0 means no battery, so every other site is unchanged. More sites get one later by setting the two values
   and adding a `battery` row to the site's points list.
2. **Size.** 2,500 kW and 10,000 kWh (2.5 MW / 10 MWh), a four-hour battery by its nameplate. NREL's representative plant uses
   four hours (primer S16); the 2.5 MW, half of Site 1's 5 MW rating, is a design choice. State of charge in SunSpec is a
   percentage of the nameplate energy (`%WHRtg`), so the usable window of decision 4 holds 8 MWh, which is 3.2 hours at full
   power before the taper and the losses.
3. **Round-trip efficiency.** 85 percent, NREL's ATB value for a plant that charges through the extra AC and DC conversions,
   which is the AC-coupled case (primer S16). The loss is split evenly: each direction keeps the square root of 0.85, about
   92.2 percent. Charging adds that share of the energy taken from the bus; discharging draws the delivered energy divided by that
   share. Real values vary with temperature, rate, and age; none of those are modeled.
4. **State of charge.** Starts at 50 percent each time the simulator starts. Operating limits are 10 and 90 percent. Power is
   full between 20 and 80 percent and fades in a straight line to zero at 10 percent (discharging) and at 90 percent (charging).
   A step is never allowed to carry the energy past a limit.
5. **The POI.** The meter reads PV plus battery: discharging is positive (export), charging is negative. Total export is held at
   the lower of the plant rating and the plant controller's limit when that is enabled, so a discharge is reduced to fit
   (a 5 MW plant at full sun cannot discharge). The existing limit still curtails PV first and by the same rule as before.
   Charging is not limited by the available PV: it may draw from the grid, and the meter then counts the energy as imported
   (`TotWhImp`). Charging from curtailed PV and evening discharge are dispatch, which waits for Phase 3 (ADR 0014 decision 8).
6. **Control.** The plant controller (the EMS role) gets two writable nodes, only on a plant that has a battery: `BatteryMode`
   (text: `Idle`, `Charge`, or `Discharge`) and `BatterySetpoint_MW` (the size of the power, never negative, held between 0
   and the battery's rating). A value that is not recognised is ignored, as for the limit. The battery starts Idle with a zero
   setpoint. The simulator writes back what it accepted.
7. **Where the tags live in Ignition.** The two control nodes are read and written through the same OPC UA connection as the
   plant controller, but their tags are members of the **Battery UDT**, not the PlantController UDT. A site without a battery then
   has no Battery instance and no tags pointing at nodes that do not exist. The Battery UDT therefore mixes Modbus members
   (telemetry) and OPC UA members (the two controls).
8. **Registers.** The battery is one more Modbus unit, number N+3 (Site 1 has N = 4, so unit 7), with these SunSpec models
   (read-only; the gateway writes nothing to it over Modbus):
   - Model 1 (common), as for the other devices.
   - Model 713 (storage capacity): `WHRtg`, `WHAvail` (energy that could still be discharged above the 10 percent limit,
     our definition), `SoC`, `SoH`.
   - Model 802 (battery base): `WHRtg`, `WChaRteMax`, `WDisChaRteMax`, `SoCMax`, `SoCMin`, `SoC`, `DoD`, `SoH`, `NCyc`, `ChaSt`,
     `LocRemCtl`, `Typ`, `State`, and `W`. Every other point is served as not implemented.
   - Scale factors: energies and powers in thousands (SF 3), percentages in hundredths (SF -2). That holds a battery up to 65 MWh
     and 32 MW; the simulator refuses larger values rather than clamp.
   - `W` is the power at the battery's terminals as the PCS delivers it, positive while discharging. SunSpec's description of `W`
     is "total power flowing to/from the battery bank" and gives no sign, so the sign is our choice. SunSpec words the ratings
     as DC quantities; the simulator serves the AC-side rating in them (approximated).
   - "Moving" means a power of at least 0.5 kW, the point below which the served `W` reads 0. `State`: Connected while moving,
     SOC Protection when Discharge is asked for at the low limit or Charge at the high limit and nothing moves, Standby
     otherwise. `ChaSt`: Discharging or Charging while moving; when not moving, Empty or Full within half a point of a limit
     and Holding elsewhere. `NCyc` counts equivalent full cycles (energy discharged divided by the nameplate, rounded down).
     `DoD` is the share of the usable window (10 to 90 percent) that has been used. `SoH` stays 100 percent, `Typ` is
     lithium-ion, `LocRemCtl` is remote.
   - Models 124 (controls) and 714 (DC measurement) are not served.
9. **Not modeled.** Everything ADR 0014 decision 8 lists, plus: a battery limit on current or voltage, the power the PCS and
   cooling use while idle, and any link between the battery and the PV inverters' clipping (AC coupling, primer section 7).

## Consequences

- `POI_MW` on the plant controller and the meter now include the battery, so a screen that assumed POI equals PV output must not
  on a site that has a battery. `RatedMW` stays the PV nameplate and the cap above.
- A restart of the simulator resets the battery to 50 percent and Idle, as it resets the energy counters.
- The `Status` node does not change: it is Curtailed, Producing while the POI is above zero, and Standby otherwise, so it reads
  Standby while the battery charges from the grid at night (a known simplification).
- Nothing in this ADR changes the other seven sites.
