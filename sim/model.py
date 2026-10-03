"""Plant model for Site 1: the physics chain for four inverters, the plant controller limit, and the POI meter.

Follows the chain in Layer Card 1. Decisions: ADR 0006 (plant size), ADR 0008 (site, orientation, clouds).
Defaults marked "assumption" are values chosen here inside a documented range or as a plain design choice.
"""
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


class PlantModel:
    def __init__(self, config=SiteConfig()):
        self.config = config
        self._clouds = p.CloudModel(config.seed)
        self.energy_wh = 0.0
        self.limit_w = 0.0
        self.limit_enabled = False

    def set_limit(self, limit_mw, enabled):
        """The plant controller's active power limit. An enabled limit is applied immediately (Layer Card 1, step 9)."""
        self.limit_w = max(0.0, limit_mw) * 1e6
        self.limit_enabled = bool(enabled)

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

        poi_w = sum(ac_w)
        self.energy_wh += poi_w * dt_s / 3600.0
        return {
            "sun": sun,
            "cloud_factor": cloud_factor,
            "ghi_w_m2": ghi,
            "poa_w_m2": poa,
            "ambient_c": ambient_c,
            "module_c": cell_c,
            "inverter_dc_w": dc_w,
            "inverter_ac_w": ac_w,
            "inverter_unlimited_ac_w": unlimited_ac_w,
            "poi_w": poi_w,
            "energy_wh": self.energy_wh,
            "limit_enabled": self.limit_enabled,
            "limit_w": self.limit_w,
            "limit_binding": limit_binding,
        }
