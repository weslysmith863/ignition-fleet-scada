# gateway/

Gateway state that lives inside a gateway's data volume rather than in a project, saved here so a factory reset can be
rebuilt from Git.

- `site1/udt-types.json`: the UDT definitions on the site1 gateway (`Inverter`, `Weather`, `Meter`), written by
  `python -m generator.export_types site1`. Run it after any UDT edit in Designer. Members are sorted by name so Git diffs
  show real changes only.

Restoring from this file (importing the definitions back into a fresh gateway) is not automated yet; devices and instances
are rebuilt from `points/site1.csv` with `python -m generator.apply`.
