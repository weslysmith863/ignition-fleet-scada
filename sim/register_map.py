"""Print the Ignition addresses of every populated SunSpec point, for building tags by hand.

    python -m sim.register_map              # plain text
    python -m sim.register_map --markdown   # the table used in docs/points/site1-register-map.md

Addresses assume Ignition's default one-based addressing: the wire address plus one (Phase 1 finding 13). The unit ID is
the number in front of the dot, so `[Inv1]1.HR40085` is unit 1 on the device named Inv1.
"""
import argparse
import random
from datetime import datetime, timezone

from sim import sunspec
from sim.model import PlantModel, SiteConfig
from sim.sunspec_layouts import LAYOUTS

# Ignition's Modbus data-type designators. HR and HRUS were exercised in the Phase 1 spike; HRI and HRUI have not been.
DESIGNATOR = {
    "int16": "HR", "sunssf": "HR", "uint16": "HRUS", "enum16": "HRUS", "bitfield16": "HRUS", "acc16": "HRUS",
    "int32": "HRI", "acc32": "HRUI", "uint32": "HRUI", "enum32": "HRUI", "bitfield32": "HRUI",
}
DEVICES = (
    ("Inverter (units 1 to 4; unit 1 shown)", 1),
    ("Weather station (unit 5)", sunspec.WEATHER_UNIT),
    ("POI meter (unit 6)", sunspec.METER_UNIT),
)


def point_rows(unit, models):
    """(model, point, Ignition address, register type, units, scale factor) for each populated point."""
    registers = sunspec.device_registers(models)
    for model_id, values in models:
        if model_id == 1:
            continue  # the common block is identification only
        start = sunspec.find_model(registers, model_id)
        offset = 2
        for name, kind, size, sf, units in LAYOUTS[model_id]:
            if name in values and kind != "string":
                address = sunspec.BASE_ADDRESS + start + offset + 1  # one-based for Ignition
                if sf is None:
                    sf_text = "-"
                elif isinstance(sf, int):
                    sf_text = "fixed %d" % sf
                else:
                    sf_text = sf
                yield model_id, name, "%d.%s%d" % (unit, DESIGNATOR[kind], address), kind, units or "", sf_text
            offset += size


def snapshot_models():
    state = PlantModel(SiteConfig(clouds_enabled=False)).step(datetime(2026, 6, 21, 18, 50, tzinfo=timezone.utc), 1.0)
    return sunspec.all_device_models(state, SiteConfig(), random.Random(0), noise=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    devices = snapshot_models()
    for title, unit in DEVICES:
        rows = list(point_rows(unit, devices[unit]))
        if args.markdown:
            print("## %s\n" % title)
            print("| Model | Point | Ignition address | Register type | Units | Scale factor |")
            print("|---|---|---|---|---|---|")
            for model_id, name, address, kind, units, sf in rows:
                print("| %d | `%s` | `%s` | %s | %s | %s |" % (model_id, name, address, kind, units or "", sf))
            print()
        else:
            print("\n%s" % title)
            for model_id, name, address, kind, units, sf in rows:
                print("  %3d  %-12s %-14s %-10s %-6s %s" % (model_id, name, address, kind, units, sf))


if __name__ == "__main__":
    main()
