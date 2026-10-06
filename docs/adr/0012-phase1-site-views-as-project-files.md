# ADR 0012: Site 1 views are project files in the repo, deployed through the REST API

Status: Accepted (2026-10-05). The no-login setting is for development only; revisit before any shared or demo deployment.

## Context

Phase 1 needs Site 1 screens. Perspective views are JSON files in an Ignition project folder, and the gateway's project API can
import a project zip (ADR 0005, finding 29). Wes has hand-built Perspective views before (DosingControl) and chose, on
2026-10-05, to have the views built as files and deployed by the agent, so the project shows what the API can do. He is still
quizzed on how a view gets its data, how history reaches a chart, and how the project is deployed.

## Decision

1. **The views live in `projects/site/`** and are deployed with `python -m generator.deploy_project site1 projects/site`. The tool
   zips the folder, imports it, and asks for a scan. It refuses to replace an existing project without `--overwrite`, because the
   repo copy is the source of truth: a redeploy discards edits made in Designer.
2. **One project, `site`, with no parent.** Decision D6 (core, site, fleet with inheritance) takes effect in Phase 2, when a second site
   gateway needs the same views. Until then `core` would be an empty shell.
3. **Three pages:** `/` Overview (four KPI cards and a row of inverter cards), `/trends` (a Power Chart of inverter output, plant
   output, and sunlight), `/controller` (the active power limit and its enable switch, with read-backs). A `Header` view with
   links is embedded in each page.
4. **Templating inside the project.** `InverterCard` takes one parameter, `inverter`, and finds its tags with indirect tag bindings
   (`[default]Inverters/{inverter}/ACPower_kW`). A flex repeater on the Overview lists the inverters as parameter sets, so a fifth
   inverter is one more entry. `Kpi` takes `title`, `text`, and `accent`, so one view makes every card.
5. **Tag paths are absolute with the `default` provider** (D25: every site gateway has the same tree). At the hub a site's tags sit under
   its remote provider, so the fleet views will need a provider parameter or inheritance; that is a Phase 2 decision.
6. **Number formatting uses expression bindings** (`numberFormat(...)`), not the format transform, whose JSON keys were not
   confirmed (finding 31). View parameters are declared as inputs (finding 31).
7. **History comes from the SQL Historian provider `Historian` (ADR 0011).** The Power Chart pens use tag paths, and the tags'
   own history settings decide what exists to chart. Only the three logged members appear in the chart.

## Dev-only relaxation

The `site` project has no authentication and the Controller page writes the plant limit through the gateway to the simulator's
OPC UA server. Anyone who can reach port 8091 can open it and change the limit. That is acceptable for a simulator on a loopback
port. For any shared deployment it needs an identity provider, security levels on the pages and on tag writes, and a decision
about who may curtail a plant. This is the same kind of local-only shortcut as ADR 0004 and ADR 0010.

## Consequences

- The Maker "Personal Use Only" notice has to be accepted by a person in the browser on every new session (finding 33).
- Verified on 2026-10-05 by reading the rendered page and the gateway log: all three pages show live values, the four inverter
  cards show their own data, and the chart shows the earlier cloud dips from the historian. **Not verified:** the Controller
  page's write path (the numeric field and the switch), which needs a click from a person.
- Layer Card 2 explains how the layer works. A fifth inverter, a second site, and the BESS pages all start from these templates.
