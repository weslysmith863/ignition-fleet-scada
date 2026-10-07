"""Plant model for Site 1: the physics chain for four inverters, the plant controller limit, and the POI meter.

Follows the chain in Layer Card 1. Decisions: ADR 0006 (plant size), ADR 0008 (site, orientation, clouds).
Defaults marked "assumption" are values chosen here inside a documented range or as a plain design choice.
"""
import math
from dataclasses import dataclass

from sim import physics as p


@dataclass(frozen=True)
class SiteConfig:
    latitude_deg: float = 31.0  # ADR 0008, illustrative west Texas
    longitude_deg: float = -102.0
    tilt_deg: float = 31.0  # ADR 0008: fixed tilt near the latitude, facing south
    surface_azimuth_deg: float = 180.0
    albedo: float = 0.25  # pvlib's default
    inverters: int = 4  # ADR 0006
    inverter_ac_w: float = 1.25e6  # ADR 0006, per inverter
    ilr: float = 1.34  # ADR 0006: module nameplate divided by inverter AC rating
    gamma: float = -0.0035  # assumption: inside the documented range of -0.002 to -0.005 per degree C
    ross_k: float = 0.0208  # documented typical value for a free-standing system
    eta_nom: float = 0.96  # PVWatts defaults
    eta_ref: float = 0.9637
    ambient_mean_c: float = 25.0  # design choice
    ambient_amplitude_c: float = 8.0  # design choice
    clouds_enabled: bool = True
    seed: int = 1
    # The battery (ADR 0016). battery_w is the PCS's AC rating and battery_wh the nameplate energy; 0 means no battery.
    battery_w: float = 0.0
    battery_wh: float = 0.0
    battery_efficiency: float = 0.85  # round trip, NREL ATB for the AC-coupled case; split evenly between the two directions
    battery_soc_start: float = 0.5  # design choice
    battery_soc_min: float = 0.10  # design choice
    battery_soc_max: float = 0.90  # design choice
    battery_taper: float = 0.10  # design choice: SoC distance over which power fades to zero at each limit

    @property
    def has_battery(self):
        return self.battery_w > 0.0 and self.battery_wh > 0.0


BATTERY_MODES = ("Idle", "Charge", "Discharge")


def _fraction(value):
    return max(0.0, min(1.0, value))


class PlantModel:
    def __init__(self, config=SiteConfig()):
        self.config = config
        self._clouds = p.CloudModel(config.seed)
        self.energy_wh = 0.0  # exported at the POI
        self.energy_import_wh = 0.0
        self.inverter_energy_wh = [0.0] * config.inverters
        self.limit_w = 0.0
        self.limit_enabled = False
        self.battery_mode = "Idle"
        self.battery_setpoint_w = 0.0
        self.battery_stored_wh = config.battery_wh * config.battery_soc_start
        self.battery_discharged_wh = 0.0

    def set_limit(self, limit_mw, enabled):
        """The plant controller's active power limit. An enabled limit is applied immediately (Layer Card 1, step 9)."""
        self.limit_w = max(0.0, limit_mw) * 1e6
        self.limit_enabled = bool(enabled)

    def set_battery(self, mode, setpoint_mw):
        """The plant controller's battery command (ADR 0016 decision 6): a mode and the size of the power, held between 0 and the
        battery's rating. An unknown mode or a setpoint that is not a finite number is ignored. Returns what is now in force."""
        if mode in BATTERY_MODES:
            self.battery_mode = mode
        if isinstance(setpoint_mw, (int, float)) and not isinstance(setpoint_mw, bool) and math.isfinite(setpoint_mw):
            self.battery_setpoint_w = min(max(float(setpoint_mw), 0.0) * 1e6, self.config.battery_w)
        return self.battery_mode, self.battery_setpoint_w / 1e6

    def _battery_step(self, pv_w, dt_s):
        """Advance the battery by dt_s seconds and return its power at the POI in watts, positive while discharging."""
        cfg = self.config
        if not cfg.has_battery:
            return 0.0
        eta = cfg.battery_efficiency ** 0.5  # the same share is lost charging and discharging
        stored_min, stored_max = cfg.battery_wh * cfg.battery_soc_min, cfg.battery_wh * cfg.battery_soc_max
        soc = self.battery_stored_wh / cfg.battery_wh
        hours = dt_s / 3600.0
        if self.battery_mode == "Discharge":
            power = min(self.battery_setpoint_w, cfg.battery_w * _fraction((soc - cfg.battery_soc_min) / cfg.battery_taper))
            cap_w = min(cfg.inverters * cfg.inverter_ac_w, self.limit_w) if self.limit_enabled else cfg.inverters * cfg.inverter_ac_w
            power = min(power, max(0.0, cap_w - pv_w))  # total export stays inside the plant rating and any limit
            if hours > 0.0:
                power = min(power, max(0.0, self.battery_stored_wh - stored_min) * eta / hours)  # never past the limit
            self.battery_stored_wh -= power / eta * hours
            self.battery_discharged_wh += power * hours
            return power
        if self.battery_mode == "Charge":
            power = min(self.battery_setpoint_w, cfg.battery_w * _fraction((cfg.battery_soc_max - soc) / cfg.battery_taper))
            if hours > 0.0:
                power = min(power, max(0.0, stored_max - self.battery_stored_wh) / eta / hours)
            self.battery_stored_wh += power * eta * hours
            return -power
        return 0.0

    def step(self, now_utc, dt_s):
        """Advance the model by dt_s seconds to now_utc and return the state as a dict."""
        cfg = self.config
        sun = p.sun_position(now_utc, cfg.latitude_deg, cfg.longitude_deg)
        extra = p.extraterrestrial_irradiance(now_utc)
        ghi_clear = p.haurwitz_ghi(sun.cos_zenith)
        cloud_factor = self._clouds.step(dt_s) if cfg.clouds_enabled else 1.0
        ghi = ghi_clear * cloud_factor
        dni, dhi = p.erbs_split(ghi, sun.cos_zenith, sun.zenith_deg, extra)
        poa, _, _, _ = p.poa_fixed_tilt(ghi, dni, dhi, sun, cfg.tilt_deg, cfg.surface_azimuth_deg, cfg.albedo)
        ambient_c = p.ambient_temp_c(sun.solar_time_h, cfg.ambient_mean_c, cfg.ambient_amplitude_c)
        cell_c = p.ross_cell_temp_c(poa, ambient_c, cfg.ross_k)

        module_dc0_w = cfg.inverter_ac_w * cfg.ilr
        inverter_dc_limit_w = cfg.inverter_ac_w / cfg.eta_nom
        dc_w = [p.pvwatts_dc_w(poa, cell_c, module_dc0_w, cfg.gamma) for _ in range(cfg.inverters)]
        unlimited_ac_w = [p.pvwatts_inverter_ac_w(dc, inverter_dc_limit_w, cfg.eta_nom, cfg.eta_ref) for dc in dc_w]

        total_unlimited_w = sum(unlimited_ac_w)
        limit_binding = self.limit_enabled and self.limit_w < total_unlimited_w
        scale = self.limit_w / total_unlimited_w if limit_binding else 1.0  # shared out in proportion
        ac_w = [a * scale for a in unlimited_ac_w]

        pv_w = sum(ac_w)
        battery_w = self._battery_step(pv_w, dt_s)
        poi_w = pv_w + battery_w
        self.energy_wh += max(poi_w, 0.0) * dt_s / 3600.0
        self.energy_import_wh += max(-poi_w, 0.0) * dt_s / 3600.0
        for i, ac in enumerate(ac_w):
            self.inverter_energy_wh[i] += ac * dt_s / 3600.0
        battery_soc = self.battery_stored_wh / cfg.battery_wh if cfg.has_battery else 0.0
        return {
            "sun": sun,
            "cloud_factor": cloud_factor,
            "ghi_w_m2": ghi,
            "dni_w_m2": dni,
            "dhi_w_m2": dhi,
            "poa_w_m2": poa,
            "ambient_c": ambient_c,
            "module_c": cell_c,
            "inverter_dc_w": dc_w,
            "inverter_ac_w": ac_w,
            "inverter_unlimited_ac_w": unlimited_ac_w,
            "pv_w": pv_w,
            "poi_w": poi_w,
            "energy_wh": self.energy_wh,
            "energy_import_wh": self.energy_import_wh,
            "inverter_energy_wh": list(self.inverter_energy_wh),
            "limit_enabled": self.limit_enabled,
            "limit_w": self.limit_w,
            "limit_binding": limit_binding,
            "battery_mode": self.battery_mode,
            "battery_setpoint_w": self.battery_setpoint_w,
            "battery_w": battery_w,
            "battery_soc": battery_soc,
            "battery_stored_wh": self.battery_stored_wh,
            "battery_discharged_wh": self.battery_discharged_wh,
        }
