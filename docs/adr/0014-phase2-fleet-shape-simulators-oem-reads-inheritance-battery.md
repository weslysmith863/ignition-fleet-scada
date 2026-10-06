# ADR 0014: Phase 2 fleet shape, simulators, OEM reads, project inheritance, and battery scope

Status: Accepted (2026-10-06), decisions 1 to 9. Decisions 1 to 8 came from the design questions; decision 9 was added the same
day after a check of the simulator and approved by Wes. Decision D6 (core, site, fleet projects with inheritance) was deferred by
ADR 0012 and takes effect here.

## Context

Phase 2 builds the fleet: a second site gateway, remote tag providers on the hub, six OEM-integrated sites, a battery model,
project inheritance, and fleet views. The gate is eight sites live from the points list. Site 1 is one 5 MWac plant with four
inverters on one simulator (ADR 0006, ADR 0013). The design questions were settled in two batches on 2026-10-06, each with a
recommendation that Wes accepted. Vocabulary and the shape of the layer are in
[Layer Card 3](../layer-cards/03-fleet-and-templating.md).

## Decision

1. **Fleet mix and order.** Eight sites: Site 1 (built), Site 2 (a second site gateway), and six OEM-integrated sites,
   `oem1` to `oem6`, which the hub reads directly. Build Site 2 first, then `oem1`. After `oem1` is live, decide whether to go
   on to eight sites or stop at five (Site 1, Site 2, `oem1` to `oem3`), the cut line in the handoff plan.
2. **Site 2 shape.** Six inverters of 1,250 kW (7.5 MWac) and a battery. Same latitude and longitude as Site 1, a different
   seed, so the two plants' clouds do not move together. A different location would cost work for little gain. Battery sizing
   waits for the domain primer, part 2 (decision 8).
3. **A second simulator container, `sim2`,** built from the same image as `sim`, with the plant shape set by environment
   variables. Each container is its own computer, so both listen on 15020 (Modbus) and 14840 (OPC UA) with no clash. The
   gateways reach `sim:15020` and `sim2:15020`. The points list's `host` column stays the only thing that picks a site's
   simulator.
4. **Remote tag providers on the hub are named by site ID:** `site1`, `site2`. Site 1's inverter power appears on the hub as
   `[site1]Inverters/Inv1/ACPower_kW`. A fleet view takes a site ID as a parameter and builds the path from it.
5. **OEM-integrated sites are read over Modbus TCP,** with the same SunSpec register map and the same UDTs. The generator
   creates the devices on the hub from the same points-list columns (`host`, `port`, `unit_id`). Each OEM site gets its own
   realtime tag provider on the hub, named by site ID (`oem1` to `oem6`), so every site's paths have the same shape:
   `[site1]...`, `[oem3]...`. The generator's `site` column must then map to a gateway and a provider.
6. **OEM plants are simulated by six more containers,** `oem1` to `oem6`, from the same image, written with a Compose YAML
   anchor so each service is a few lines. One plant stays one process. Rejected: one process serving six plants on six ports,
   which saves Compose lines but needs new simulator code and adds a failure mode.
7. **Three projects with inheritance.** `core` (inheritable, no parent) holds the reusable pieces: Header, InverterCard, Kpi,
   shared styles, and a script that builds tag paths. `site` (parent `core`) holds Overview, Trends, and Controller and deploys
   to both site gateways. `fleet` (parent `core`) holds the fleet overview and site-detail pages and deploys to the hub.
   InverterCard already takes its tag path from the view that places it, so the hub can reuse it with `[site1]...` paths. The
   agent writes the project files; Wes checks the parent setting in Designer by predicting where it lives, then finding it (he
   may choose to create the first parent link by hand instead).
8. **Battery scope.** The battery is AC-coupled: it has its own power conversion system (PCS, the battery's inverter) on the AC
   side next to the PV inverters, so the PV inverters are unchanged. Modeled: state of charge (SoC) integrating power; a power
   limit that tapers near empty and full; one round-trip efficiency number; Idle, Charge, and Discharge modes with a MW setpoint
   from the plant controller; a POI meter that reads PV plus battery. Not modeled: temperature, degradation, cell-level BMS
   detail, ramp limits, auxiliary load, and automatic dispatch (charging from curtailed solar, evening discharge), which waits
   for the Phase 3 fault and dispatch scenarios. Domain primer part 2 (SoC, PCS, BMS, round-trip efficiency, with sources) is
   written first, and battery sizing and register layout get their own ADR after it.
9. **Unit IDs follow the inverter count.** Inverters are units 1 to N, the weather station is N+1, and the meter is
   N+2. Site 1 (N = 4) is unchanged: weather 5, meter 6. The inverter model name served in the SunSpec common block
   (`SIM-INV-1250`) should follow the rating too. Reason: the simulator fixes the units (see Checked below).

## Checked and not yet checked

**Checked on 2026-10-06:**
- The simulator cannot yet serve a plant with other than four inverters. `sim/sunspec.py:24` fixes `INVERTER_UNITS = (1, 2, 3, 4)`,
  with the weather station at 5 and the meter at 6, so `SiteConfig(inverters=6)` raises `IndexError` on the first tick (run
  directly). The plant model itself takes the inverter count and the rating from `SiteConfig`. The command line does not expose
  them yet, and the register-map document is generated for Site 1 only. This corrects a guess made in the design questions that
  the register map would follow the inverter count.
- `projects/site/project.json` has `"inheritable": false` and `"parent": ""`, and the project holds the views Controller,
  Header, InverterCard, Kpi, Overview, and Trends.

**Guesses and understandings still to test** (each gets a short spike before anything depends on it):
- The hub's local name for a remote provider can differ from the site's own provider name (`default`).
- The REST API can create additional tag providers on the hub, and Maker does not limit how many. If either fails, the fallback
  is one folder per OEM site (`oem1/...`) in the hub's default provider, and fleet views build paths from a base path in place
  of a provider name.
- A child project can inherit only from a parent on the same gateway, so `core` deploys to all three gateways and
  `generator.deploy_project` runs once per gateway and project.
- The extra containers are light next to the two Ignition gateways. Measure with `docker stats`.
- General knowledge, unsourced: real owners usually receive OEM data through OPC UA or protocol gateways, and DNP3 is not
  offered in Maker. Modbus for the OEM sites is therefore an approximation, and the project says so.

## Consequences

- **Twelve containers** when finished: hub, site1, site2, postgres, sim, sim2, and `oem1` to `oem6`. Starting everything stays
  `docker.exe compose up -d --build`.
- **Generator work** (each piece with tests and a dry run, never overwriting hand-built objects): UDT import from
  `gateway/site1/udt-types.json`; creating the PlantController OPC connection and instance and the `Historian` provider; a
  points-list kind for the plant controller; a gateway-and-provider mapping for the `site` column; a points file for Site 2.
- **Simulator work:** take the plant shape from environment variables, apply decision 9, then the battery model after the
  primer.
- **Prerequisites that need Wes:** release the DosingControl Maker license and regenerate its token in the account portal (Maker
  allows three active gateways); add the Site 2 key and token names to `.env` and `.env.example`; create the `API_RW` level, the
  write permission, and the API key on site2. The agent prepares the `site2` service and volume and sets the hub whitelist to
  `site1,site2`. Site 2 uses plaintext on the Gateway Network like Site 1 (ADR 0004), so the hub needs no change for SSL.
  Nothing is wiped or recreated without asking.
- **Still open for later ADRs:** the battery's register layout and sizing; fleet alarm behavior (Phase 3); what the OEM sites do
  during fault scenarios.
