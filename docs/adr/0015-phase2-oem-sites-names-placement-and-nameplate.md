# ADR 0015: OEM-integrated sites: names, where their objects live, and the nameplate tag

Status: Accepted (2026-10-06) as the working details of ADR 0014 decisions 5 and 6. Wes has not reviewed it yet.

## Context

ADR 0014 settled how the hub reads the six OEM-integrated sites: over Modbus TCP, with the same SunSpec register map and UDTs, one
simulator container per plant, and one tag provider per site named by the site ID. Building the first one needed a few more
choices: how the sites are named, where their devices and tags live, what the fleet screen can assume about a site that has no
plant controller, and how the hub keeps history. These are design choices, not tested facts.

## Decision

1. **Names.** The sites are `oem1` to `oem6`. Each has its own points file (`points/oem1.csv`), a simulator service of the same
   name, and a provider of the same name on the hub. The `host` column of a site's rows is its simulator service.
2. **Where the objects live.** `generator/sites.py` is the one place that says so. A site gateway (`site1`, `site2`) runs its own
   site: its devices and tags are on that gateway, in `default`. An OEM site has no gateway: its devices are on the hub and its
   tags are in a local provider named for the site. Device names are unique across a gateway, so an OEM device is named
   `<site>_<device>` (`oem1_Inv1`); its tag keeps the plain name (`Inverters/Inv1`), so every site has the same tag layout and a
   view can read `[<site>]Inverters/{inverter}/...` for any of them. The instance's `Device` parameter holds the prefixed name.
3. **Shapes.** Each site differs from the others, so one points list is shown producing different plants. `oem1` is built first:
   three inverters of 1,500 kW (4.5 MWac), seed 3. The plan for the rest, which are not built yet and may change: `oem2` six of
   1,000 kW, `oem3` two of 2,000 kW, `oem4` eight of 1,250 kW, `oem5` four of 750 kW, `oem6` five of 1,500 kW. Unit IDs follow the
   inverter count (ADR 0014 decision 9).
4. **The simulators.** They share one definition in `docker-compose.yml` (`x-oem-sim`): the `sim` image, read over Modbus only, so
   the OPC UA plant controller is switched off and the health check waits for the Modbus port alone. Nothing is published on the
   PC. Only the hub reads them.
5. **The nameplate tag.** An OEM site has no plant controller, so nothing on it says what its rating is. The generator therefore
   makes a memory tag `Site/RatedMW` for every site, from the points list (the sum of the inverter ratings), and the fleet screen
   reads `[<site>]Site/RatedMW`. The fleet card shows only what every site has: meter output, the share of its rating, sunlight
   from the weather station, and a status derived from the output (Producing or Standby). Curtailment and the limit controls stay
   on a site gateway's own page.
6. **History on the hub.** The UDT history settings name a provider called `Historian`, so the hub gets the `fleetdb` connection
   and a `Historian` provider, made by `generator.connections hub`. Fleet history shares the one PostgreSQL.

## Consequences

- The generator maps a site to its gateway and provider (`generator.apply`, `generator.providers`, `generator.retarget`), and the
  fleet consistency test checks the OEM points files against the compose file and that device names do not collide on the hub.
- Build `oem1` first. After it is live, decide whether to go on to eight sites or stop at five (ADR 0014 decision 1).
- The fleet card no longer shows "power limit active" for a site gateway; the site's own page still does.
- Not modeled: anything vendor-specific about an OEM site's controls or alarms. The Modbus read is an approximation of how an
  owner receives vendor data (ADR 0014).
