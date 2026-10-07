# Glossary

Short definitions for the solar terms used in this repo. The explanations, with sources, are in the primer
([01-solar-plant-primer.md](01-solar-plant-primer.md)). Battery terms are in the second table, from part 2 ([02-battery-primer.md](02-battery-primer.md)).

| Term | Plain meaning | Unit |
|---|---|---|
| Irradiance | Sunlight power per area | W/m² |
| GHI | Irradiance on a flat, level surface (all sky light plus the direct beam) | W/m² |
| DNI | Irradiance from the sun's disc, on a surface facing the sun | W/m² |
| DHI | Irradiance scattered by the sky, on a flat, level surface | W/m² |
| POA | Irradiance on the tilted or tracking panel face; the one that drives power | W/m² |
| Pyranometer | Sensor that measures irradiance | |
| PV cell, module, array | A cell makes electricity from light; cells make a module (panel); modules make an array | |
| String | Modules wired in series (general knowledge) | |
| DC, AC | Steady one-way current (panels); alternating current (the grid) | |
| Nameplate rating | A panel's output under STC | W |
| STC | Standard test conditions: 1000 W/m², 25 °C cell temperature, air mass 1.5 spectrum | |
| Inverter | Converts DC to AC | |
| I-V curve | The current and voltage combinations an array can operate at for given sunlight | |
| MPP, MPPT | The point on the I-V curve with the most power; the inverter function that stays on it | |
| MWac, MWdc | Plant size counted by inverter AC ratings, or by module nameplates | MW |
| ILR, DC:AC ratio | DC capacity divided by AC capacity | ratio |
| Clipping | Output flattening at the inverter's AC rating when the array could supply more | |
| Curtailment | Output held below what the plant could produce, by instruction | |
| Capacity factor | Average output divided by the output at full rating around the clock | % |
| Step-up transformer | Raises the plant's voltage for the grid (general knowledge) | |
| POI | Point of interconnection: where the plant's facilities meet the transmission provider's system | |
| Revenue meter | The meter that measures what the plant delivers at the POI (general knowledge) | |
| Active power | Power doing useful work; what is sold | W, kW, MW |
| Reactive power | Power swinging back and forth that helps hold voltage steady | var, kvar, MVAr |
| Energy | Power accumulated over time | Wh, kWh, MWh |
| Plant controller (PPC) | Controller above the inverters that turns plant-level targets into per-inverter commands | |
| Setpoint | A target value written to a device, as opposed to a measurement read from it | |
| SunSpec | A standard that publishes register maps (lists of Modbus registers) for inverters and other devices | |
| Scale factor | A paired register that tells where the decimal point goes in another register's whole number | |

## Battery terms

| Term | Plain meaning | Unit |
|---|---|---|
| BESS | Battery energy storage system: batteries plus the equipment that charges, discharges, and protects them |  |
| Power capacity | How fast the battery can charge or discharge | kW, MW |
| Energy capacity | How much energy the battery can hold | kWh, MWh |
| Duration | Hours the battery can discharge at its power capacity before it is empty: energy capacity divided by power capacity | hours |
| State of charge (SoC) | How full the battery is; usually estimated, not measured | % |
| Depth of discharge (DoD) | How much of the capacity has been used | % |
| State of health (SoH) | The share of battery life remaining | % |
| BMS | Battery management system: measures voltage, current, and temperature, estimates SoC and SoH, and protects the battery |  |
| PCS | Power conversion system: the battery's bidirectional inverter; the inverter/charger |  |
| EMS | Energy management system: decides the charge or discharge power and sends it to the PCS as a command |  |
| Round-trip efficiency | Share of the energy put in that comes back out over a charge and discharge cycle | % |
| AC-coupled | The battery has its own inverter and meets the PV on the AC side |  |
| DC-coupled | The battery shares the PV's DC side and one bidirectional inverter |  |
| Cycle | One charge and discharge of the battery; the cycle count measures wear |  |
