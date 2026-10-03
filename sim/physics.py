"""Physics chain for the Phase 1 simulator (Layer Card 1). Standard library only.

Each function names its source (the L-tags are in docs/layer-cards/01-field-devices-and-simulator.md) and its label:
modeled (a published equation used as published), approximated (simplified), or design choice (no published basis).
Irradiance is in W/m2, power in W, temperature in degrees C, angles in degrees unless a name ends in _rad.
Times are UTC, so daylight saving never enters.
"""
import calendar
import math
import random
from typing import NamedTuple

SOLAR_CONSTANT_W_M2 = 1366.1  # pvlib's default solar constant [L3]


class SunPosition(NamedTuple):
    cos_zenith: float
    zenith_deg: float
    azimuth_deg: float  # clockwise from north
    solar_time_h: float  # true solar time in hours, 0 to 24


def _hours(dt_utc):
    return dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0 + dt_utc.microsecond / 3.6e9


def fractional_year_rad(dt_utc):
    """NOAA fractional year [L1]. NOAA writes the hour as a whole number; the fractional hour is used here."""
    days_in_year = 366 if calendar.isleap(dt_utc.year) else 365
    doy = dt_utc.timetuple().tm_yday
    return 2.0 * math.pi / days_in_year * (doy - 1 + (_hours(dt_utc) - 12.0) / 24.0)


def equation_of_time_min(g):
    """NOAA equation of time in minutes [L1]."""
    return 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                     - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))


def declination_rad(g):
    """NOAA solar declination in radians [L1]."""
    return (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))


def sun_position(dt_utc, lat_deg, lon_deg):
    """Approximated: geometric zenith, no refraction correction. Longitude is positive east.

    Solar time follows NOAA [L1] with the time zone term dropped because the clock is UTC. The azimuth uses the standard
    relation cos(az) = (sin(decl) - sin(lat) cos(zen)) / (cos(lat) sin(zen)), east of the meridian before solar noon
    and west after; the sign in the extracted NOAA text was ambiguous, so tests pin noon, sunrise, and sunset.
    """
    g = fractional_year_rad(dt_utc)
    decl = declination_rad(g)
    tst_min = _hours(dt_utc) * 60.0 + equation_of_time_min(g) + 4.0 * lon_deg
    hour_angle_deg = (tst_min / 4.0) % 360.0 - 180.0
    lat = math.radians(lat_deg)
    cos_z = (math.sin(lat) * math.sin(decl)
             + math.cos(lat) * math.cos(decl) * math.cos(math.radians(hour_angle_deg)))
    cos_z = max(-1.0, min(1.0, cos_z))
    zen = math.acos(cos_z)
    sin_z = math.sin(zen)
    if sin_z < 1e-9:
        azimuth = 180.0  # sun overhead: azimuth is undefined
    else:
        c = (math.sin(decl) - math.sin(lat) * cos_z) / (math.cos(lat) * sin_z)
        angle = math.degrees(math.acos(max(-1.0, min(1.0, c))))
        azimuth = angle if hour_angle_deg < 0 else 360.0 - angle
    return SunPosition(cos_z, math.degrees(zen), azimuth, (tst_min / 60.0) % 24.0)


def extraterrestrial_irradiance(dt_utc):
    """Irradiance above the atmosphere on a plane facing the sun. Spencer method as in pvlib [L3]."""
    b = 2.0 * math.pi / 365.0 * (dt_utc.timetuple().tm_yday - 1)
    r_over_r0_sq = (1.00011 + 0.034221 * math.cos(b) + 0.00128 * math.sin(b)
                    + 0.000719 * math.cos(2 * b) + 7.7e-05 * math.sin(2 * b))
    return SOLAR_CONSTANT_W_M2 * r_over_r0_sq


def haurwitz_ghi(cos_zenith):
    """Clear-sky GHI. Haurwitz model [L2]. Approximated: depends on the zenith only."""
    if cos_zenith <= 0.0:
        return 0.0
    return 1098.0 * cos_zenith * math.exp(-0.059 / cos_zenith)


def clearness_index(ghi, cos_zenith, extraterrestrial):
    """GHI divided by the extraterrestrial irradiance on a horizontal plane, clipped as in pvlib [L3]."""
    kt = ghi / (extraterrestrial * max(cos_zenith, 0.065))
    return max(0.0, min(2.0, kt))


def erbs_split(ghi, cos_zenith, zenith_deg, extraterrestrial):
    """Split GHI into (DNI, DHI). Erbs diffuse fraction [L3]. Approximated."""
    kt = clearness_index(ghi, cos_zenith, extraterrestrial)
    if kt <= 0.22:
        diffuse_fraction = 1.0 - 0.09 * kt
    elif kt <= 0.8:
        diffuse_fraction = 0.9511 - 0.1604 * kt + 4.388 * kt ** 2 - 16.638 * kt ** 3 + 12.336 * kt ** 4
    else:
        diffuse_fraction = 0.165
    dhi = diffuse_fraction * ghi
    dni = (ghi - dhi) / cos_zenith if cos_zenith > 0.0 else 0.0
    if zenith_deg > 87.0 or ghi < 0.0 or dni < 0.0:  # pvlib's guard for the low sun
        return 0.0, ghi
    return dni, dhi


def poa_fixed_tilt(ghi, dni, dhi, sun, tilt_deg, surface_azimuth_deg=180.0, albedo=0.25):
    """Irradiance on a fixed tilted surface: beam + isotropic sky diffuse + ground reflection [L4]. Approximated.

    Returns (poa, beam, sky_diffuse, ground_reflected). The default albedo is pvlib's default [L4].
    """
    tilt = math.radians(tilt_deg)
    zen = math.radians(sun.zenith_deg)
    cos_aoi = (math.cos(tilt) * math.cos(zen)
               + math.sin(tilt) * math.sin(zen) * math.cos(math.radians(sun.azimuth_deg - surface_azimuth_deg)))
    cos_aoi = max(-1.0, min(1.0, cos_aoi))
    beam = max(dni * cos_aoi, 0.0)
    sky = dhi * (1.0 + math.cos(tilt)) / 2.0
    ground = ghi * albedo * (1.0 - math.cos(tilt)) / 2.0
    return beam + sky + ground, beam, sky, ground


def ross_cell_temp_c(poa, ambient_c, k=0.0208):
    """Cell temperature, Ross model [L5]: ambient + k x POA. k in K m2/W; 0.0208 is the documented typical value for a
    free-standing system. Approximated: wind is not modeled."""
    return ambient_c + k * poa


def pvwatts_dc_w(poa, cell_c, p_dc0_w, gamma, ref_c=25.0):
    """DC power of the modules, PVWatts [L6]. p_dc0_w is the nameplate at 1000 W/m2 and the reference cell temperature."""
    return poa / 1000.0 * p_dc0_w * (1.0 + gamma * (cell_c - ref_c))


def pvwatts_inverter_ac_w(p_dc_w, p_dc_limit_w, eta_nom=0.96, eta_ref=0.9637):
    """AC power of an inverter, PVWatts [L6]: an efficiency curve, then clipping at the AC rating.

    p_dc_limit_w is the inverter's DC input limit; its AC rating is eta_nom x p_dc_limit_w. The efficiency curve is
    generic, not a real unit's, so it is approximated; the clipping is the modeled part.
    """
    p_ac0 = eta_nom * p_dc_limit_w
    if p_dc_w == 0.0:
        return 0.0
    zeta = p_dc_w / p_dc_limit_w
    eta = eta_nom / eta_ref * (-0.0162 * zeta - 0.0059 / zeta + 0.9858)
    return max(0.0, min(p_ac0, eta * p_dc_w))


def ambient_temp_c(solar_time_h, mean_c=25.0, amplitude_c=8.0):
    """Design choice: a daily cosine, warmest at 15:00 solar time and coolest at 03:00. No seasons, no weather."""
    return mean_c + amplitude_c * math.cos(2.0 * math.pi * (solar_time_h - 15.0) / 24.0)


class CloudModel:
    """Design choice with no published basis: seeded passing clouds that dim clear-sky irradiance.

    Between clouds the factor is 1.0. A cloud starts at random, has a random depth and duration, and dims the sky with a
    smooth half-sine shape. Given the same seed and the same sequence of steps, the factors repeat exactly.
    """

    def __init__(self, seed, mean_gap_s=900.0, depth_range=(0.15, 0.70), duration_range_s=(30.0, 300.0)):
        self._rng = random.Random(seed)
        self._mean_gap_s = mean_gap_s
        self._depth_range = depth_range
        self._duration_range_s = duration_range_s
        self._depth = 0.0
        self._duration_s = 0.0
        self._elapsed_s = 0.0
        self._in_cloud = False

    def step(self, dt_s):
        """Advance by dt_s seconds and return the factor (0 to 1) for the new moment."""
        if self._in_cloud:
            self._elapsed_s += dt_s
            if self._elapsed_s >= self._duration_s:
                self._in_cloud = False
        elif self._rng.random() < dt_s / self._mean_gap_s:
            self._in_cloud = True
            self._depth = self._rng.uniform(*self._depth_range)
            self._duration_s = self._rng.uniform(*self._duration_range_s)
            self._elapsed_s = 0.0
        if not self._in_cloud:
            return 1.0
        return 1.0 - self._depth * math.sin(math.pi * self._elapsed_s / self._duration_s)
