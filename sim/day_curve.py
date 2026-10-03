"""Print one simulated day through the whole chain, hour by hour (clouds off by default), to eyeball the shape.

    python -m sim.day_curve                       # clear day, 2026-06-21
    python -m sim.day_curve 2026-12-21 --limit 3  # winter day with a 3 MW plant limit

This is a look at the model's output, not a validation against real plant data.
"""
import argparse
from datetime import datetime, timedelta, timezone

from sim.model import PlantModel, SiteConfig

LOCAL_UTC_OFFSET_H = -5  # Central daylight time, for the printed local hour only


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("date", nargs="?", default="2026-06-21", help="UTC date to start from (YYYY-MM-DD)")
    parser.add_argument("--limit", type=float, default=None, help="plant MW limit to apply all day")
    parser.add_argument("--clouds", action="store_true", help="turn the seeded clouds on")
    args = parser.parse_args()

    start = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc) - timedelta(hours=LOCAL_UTC_OFFSET_H)
    model = PlantModel(SiteConfig(clouds_enabled=args.clouds))
    if args.limit is not None:
        model.set_limit(args.limit, True)

    print("local  sun_elev  GHI   POA  amb_C mod_C | DC/inv_MW AC/inv_MW | POI_MW  limit   note")
    t = start
    step_s = 60
    next_print = start
    while t < start + timedelta(hours=24):
        state = model.step(t, step_s)
        if t >= next_print:
            elev = 90.0 - state["sun"].zenith_deg
            note = ""
            if state["limit_binding"]:
                note = "curtailed (limit binding)"
            elif state["poi_w"] >= 0.9995 * 4 * 1.25e6:
                note = "clipped at the AC rating"
            if elev > 0:
                print("%02d:%02d  %6.1f  %5.0f %5.0f  %5.1f %5.1f |  %6.3f    %6.3f   | %6.3f  %-6s  %s" % (
                    (t.hour + LOCAL_UTC_OFFSET_H) % 24, t.minute, elev, state["ghi_w_m2"], state["poa_w_m2"],
                    state["ambient_c"], state["module_c"], state["inverter_dc_w"][0] / 1e6,
                    state["inverter_ac_w"][0] / 1e6, state["poi_w"] / 1e6,
                    ("%.1f" % (state["limit_w"] / 1e6)) if state["limit_enabled"] else "off", note))
            next_print += timedelta(hours=1)
        t += timedelta(seconds=step_s)
    print("\nEnergy over the day: %.1f MWh" % (model.energy_wh / 1e6))


if __name__ == "__main__":
    main()
