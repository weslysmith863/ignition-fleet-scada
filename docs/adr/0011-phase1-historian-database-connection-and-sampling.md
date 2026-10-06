# ADR 0011: Phase 1 database connection, SQL Historian, and history sampling

Status: Accepted (2026-10-05). The sampling numbers are choices, not measurements; revisit them when the views and the fleet
show what volume and resolution are really needed.

## Context

ADR 0007 decision 3 chose the SQL Historian on PostgreSQL for Site 1. This ADR records how it was set up and what is logged.

## Decision

1. **Database connection `fleetdb`** to PostgreSQL at `postgres:5432` (the Compose service name; both are containers). It is
   created by `python -m generator.connections site1`, which never overwrites and reports drift. The password comes from the
   gitignored `.env`, goes through the gateway's encrypt route, and only the encrypted value is stored (finding 27).
2. **SQL Historian provider `Historian`** on `fleetdb`, created by hand in the gateway's Config pages. The provider form's
   pruning came up on at one month, a form default; history older than a month is deleted. Fine for development;
   revisit before the showcase.
3. **Only engineering members log, never the Raw folders**, and only what the views need. First set: `ACPower_kW` (Inverter
   type, so all four inverters), `POA_Wm2` (Weather), `POI_MW` (Meter). More members are added when a view needs them.
4. **Sampling for analog members:** Sample Mode On Change, minimum 5 seconds between samples, maximum 1 minute (a
   heartbeat), and a deadband sized to the unit: 1 for `ACPower_kW` (kW), 5 for `POA_Wm2` (W/m2), 0.005 for `POI_MW`
   (MW, about 5 kW). The storage provider is `Historian`. Settings live on the UDT definition, so every instance inherits them.
5. **Whole-number and on/off members** (inverter `State`, the plant controller's `LimitEnable` and `LimitActive`) will need a
   deadband of 0 or a discrete deadband style: a deadband of 1 could swallow a change between neighboring codes.

## Why these numbers

- One row a second is 86,400 rows a day per tag, and the simulator's noise would trigger a write almost every second.
  Five seconds is a compromise for a plant-scale view, not a requirement.
- The heartbeat makes a steady value look steady instead of silent. With a maximum of 0, a flat 1250 kW would have been
  written once and never again, indistinguishable from a dead link.
- Evidence (2026-10-05, a simulated cloud): flat at 1250 kW for 8 minutes gave exactly one row a minute per inverter, and when
  the cloud arrived (POA 900 to about 480 W/m2) rows came every 6 to 7 seconds while the value moved. The meter's
  `POI_MW` rows agreed with four times an inverter's `ACPower_kW` at the same instant (3.922 and 4 x 980.4).

## Consequences

- Quality is stored as a code in `dataintegrity`; 192 is Good (seen in the table).
- Ignition created the history tables itself on the first write: `sqlt_data_1_<year>_<month>` plus six `sqlth_` tables. Tag
  paths are stored lowercase and without the provider prefix (`inverters/inv1/acpower_kw`).
- A `down -v` removes the connection, the provider, and the data. The connection comes back from the generator; the provider
  and the UDT history settings come back from `gateway/site1/udt-types.json` only by hand until UDT import exists (parked).
