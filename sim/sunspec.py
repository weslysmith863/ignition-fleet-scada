"""SunSpec register maps for the simulated devices (ADR 0006, ADR 0009, Layer Card 1). Standard library only.

A device's registers are a list starting at BASE_ADDRESS: the "SunS" marker, then a chain of models (each a header of ID and
length followed by its body), then an end model. Register k of the list is at Modbus address BASE_ADDRESS + k.
Scale factors are chosen so every value fits its 16-bit register (a 1.25 MW inverter needs W_SF = 2, units of 100 W).
Raw register value = real value / 10^SF, the inverse of the rule the gateway applies.
"""
import math

from sim.sunspec_layouts import LAYOUTS

BASE_ADDRESS = 40000
INVERTER_VLL = 600.0  # assumption (ADR 0009): inverter AC voltage, line to line
METER_VLL = 34500.0  # assumption: a 34.5 kV collector-level POI meter
NOMINAL_HZ = 60.0

# SunSpec's published not-implemented values; read from a search excerpt of the specification, not its text (ADR 0009).
NOT_IMPLEMENTED = {
    "int16": 0x8000, "sunssf": 0x8000, "pad": 0x8000, "uint16": 0xFFFF, "enum16": 0xFFFF, "bitfield16": 0xFFFF,
    "acc16": 0, "int32": 0x80000000, "uint32": 0xFFFFFFFF, "enum32": 0xFFFFFFFF, "bitfield32": 0xFFFFFFFF, "acc32": 0,
}

ST_OFF, ST_SLEEPING, ST_STARTING, ST_MPPT, ST_THROTTLED = 1, 2, 3, 4, 5  # SunSpec model 103 operating states
INVERTER_UNITS = (1, 2, 3, 4)
WEATHER_UNIT = 5
METER_UNIT = 6


def raw(value, sf):
    """Real value to the whole number stored in the register: value / 10^sf."""
    return int(round(value / (10.0 ** sf)))


def _encode(kind, size, value):
    if kind == "string":
        data = str(value).encode("ascii")[: size * 2].ljust(size * 2, b"\x00")
        return [(data[i] << 8) | data[i + 1] for i in range(0, size * 2, 2)]
    value = int(value)
    if size == 1:
        low, high = (-32768, 32767) if kind in ("int16", "sunssf") else (0, 65535)
        return [max(low, min(high, value)) & 0xFFFF]
    if kind == "acc32":
        value &= 0xFFFFFFFF  # accumulators roll over
    else:
        low, high = (-2 ** 31, 2 ** 31 - 1) if kind == "int32" else (0, 2 ** 32 - 1)
        value = max(low, min(high, value)) & 0xFFFFFFFF
    return [value >> 16, value & 0xFFFF]  # SunSpec is big-endian: the high word comes first


def _not_implemented(kind, size):
    """The marker is a bit pattern, not a number, so it is written as-is and never passed through the clamping encoder."""
    if kind == "string":
        return [0] * size
    pattern = NOT_IMPLEMENTED[kind]
    return [pattern & 0xFFFF] if size == 1 else [pattern >> 16, pattern & 0xFFFF]


def model_block(model_id, values=None):
    """Header (ID, length) plus body for one model. Points not in values are served as not implemented."""
    values = values or {}
    layout = LAYOUTS[model_id]
    unknown = set(values) - {entry[0] for entry in layout}
    if unknown:
        raise KeyError("model %d has no points %s" % (model_id, sorted(unknown)))
    body = []
    for name, kind, size, *_ in layout:
        body += _encode(kind, size, values[name]) if name in values else _not_implemented(kind, size)
    return [model_id, len(body)] + body


def device_registers(models):
    """models: a list of (model_id, values). Returns the register list from BASE_ADDRESS, ending with the end model."""
    registers = [0x5375, 0x6E53]  # 'SunS'
    for model_id, values in models:
        registers += model_block(model_id, values)
    return registers + [0xFFFF, 0]


def find_model(registers, model_id):
    """Index of the model's ID register, found by walking the chain like a SunSpec client does, or None."""
    index = 2
    while index + 1 < len(registers):
        found_id, length = registers[index], registers[index + 1]
        if found_id == 0xFFFF:
            return None
        if found_id == model_id:
            return index
        index += 2 + length
    return None


def point_index(registers, model_id, point):
    """Index of the first register of a point, or None when the model or point is absent."""
    start = find_model(registers, model_id)
    if start is None:
        return None
    offset = 2
    for name, _, size, *_ in LAYOUTS[model_id]:
        if name == point:
            return start + offset
        offset += size
    return None


def _common(model_name, unit):
    return (1, {"Mn": "Fleet SCADA Sim", "Md": model_name, "Opt": "", "Vr": "0.1", "SN": "SIM-%d" % unit, "DA": unit})


def _jitter(rng, scale, noise):
    return 1.0 + (rng.gauss(0.0, scale) if noise else 0.0)


def inverter_models(unit, index, state, config, rng, noise=True):
    """Models for one inverter: common, model 103 (inverter), model 123 (read-only power-limit mirror)."""
    rating = config.inverter_ac_w
    ac = state["inverter_ac_w"][index]
    dc = state["inverter_dc_w"][index]
    vln = INVERTER_VLL / math.sqrt(3.0) * _jitter(rng, 0.002, noise)
    phase_amps = ac / (math.sqrt(3.0) * INVERTER_VLL)  # unity power factor
    hz = NOMINAL_HZ + (rng.gauss(0.0, 0.01) if noise else 0.0)
    asleep = state["poa_w_m2"] < 5.0
    throttled = state["limit_binding"] or ac >= 0.999 * rating
    st = ST_SLEEPING if asleep else (ST_THROTTLED if throttled else ST_MPPT)  # design choice (ADR 0009)
    cabinet_c = state["ambient_c"] + 5.0 + 15.0 * (ac / rating)  # design choice
    if state["limit_enabled"]:
        limit_pct = min(100.0, state["limit_w"] / (config.inverters * rating) * 100.0)
    else:
        limit_pct = 100.0
    inverter = {
        "A": raw(3.0 * phase_amps, -1), "AphA": raw(phase_amps, -1), "AphB": raw(phase_amps, -1),
        "AphC": raw(phase_amps, -1), "A_SF": -1,
        "PPVphAB": raw(INVERTER_VLL, -1), "PPVphBC": raw(INVERTER_VLL, -1), "PPVphCA": raw(INVERTER_VLL, -1),
        "PhVphA": raw(vln, -1), "PhVphB": raw(vln, -1), "PhVphC": raw(vln, -1), "V_SF": -1,
        "W": raw(ac, 2), "W_SF": 2,
        "Hz": raw(hz, -2), "Hz_SF": -2,
        "VA": raw(abs(ac), 2), "VA_SF": 2,
        "VAr": 0, "VAr_SF": 2,
        "PF": raw(100.0, -2), "PF_SF": -2,
        "WH": int(state["inverter_energy_wh"][index]), "WH_SF": 0,
        "DCW": raw(dc, 2), "DCW_SF": 2,
        "TmpCab": raw(cabinet_c, -1), "Tmp_SF": -1,
        "St": st,
        "Evt1": 0, "Evt2": 0,
    }
    controls = {  # read-only mirror of the plant limit in Phase 1
        "Conn": 1, "WMaxLimPct": raw(limit_pct, -2), "WMaxLimPct_SF": -2,
        "WMaxLimPct_WinTms": 0, "WMaxLimPct_RvrtTms": 0, "WMaxLimPct_RmpTms": 0,
        "WMaxLim_Ena": 1 if state["limit_enabled"] else 0,
    }
    return [_common("SIM-INV-1250", unit), (103, inverter), (123, controls)]


def weather_models(unit, state):
    """Models for the weather station: common, 302 irradiance (one sensor), 303 back-of-module temperature, 307 ambient."""
    return [
        _common("SIM-WEATHER", unit),
        (302, {"GHI": round(state["ghi_w_m2"]), "POAI": round(state["poa_w_m2"]),
               "DFI": round(state["dhi_w_m2"]), "DNI": round(state["dni_w_m2"])}),
        (303, {"TmpBOM": raw(state["module_c"], -1)}),  # the model's cell temperature stands in (approximated)
        (307, {"TmpAmb": raw(state["ambient_c"], -1)}),
    ]


def meter_models(unit, state, rng, noise=True):
    """Models for the POI meter: common and model 203 (three-phase wye meter)."""
    poi = state["poi_w"]
    vln = METER_VLL / math.sqrt(3.0) * _jitter(rng, 0.001, noise)
    phase_amps = poi / (math.sqrt(3.0) * METER_VLL)
    hz = NOMINAL_HZ + (rng.gauss(0.0, 0.01) if noise else 0.0)
    meter = {
        "A": raw(3.0 * phase_amps, -1), "AphA": raw(phase_amps, -1), "AphB": raw(phase_amps, -1),
        "AphC": raw(phase_amps, -1), "A_SF": -1,
        "PhV": raw(vln, 1), "PhVphA": raw(vln, 1), "PhVphB": raw(vln, 1), "PhVphC": raw(vln, 1),
        "PPV": raw(METER_VLL, 1), "PhVphAB": raw(METER_VLL, 1), "PhVphBC": raw(METER_VLL, 1),
        "PhVphCA": raw(METER_VLL, 1), "V_SF": 1,
        "Hz": raw(hz, -2), "Hz_SF": -2,
        "W": raw(poi, 3), "WphA": raw(poi / 3.0, 3), "WphB": raw(poi / 3.0, 3), "WphC": raw(poi / 3.0, 3), "W_SF": 3,
        "TotWhExp": int(state["energy_wh"] / 1000.0), "TotWhImp": 0, "TotWh_SF": 3,
    }
    return [_common("SIM-METER", unit), (203, meter)]


def all_device_models(state, config, rng, noise=True):
    """{unit id: models} for every device on the simulator's endpoint."""
    devices = {}
    for index in range(config.inverters):
        unit = INVERTER_UNITS[index]
        devices[unit] = inverter_models(unit, index, state, config, rng, noise)
    devices[WEATHER_UNIT] = weather_models(WEATHER_UNIT, state)
    devices[METER_UNIT] = meter_models(METER_UNIT, state, rng, noise)
    return devices


def all_registers(state, config, rng, noise=True):
    """{unit id: register list} for every device."""
    return {unit: device_registers(models) for unit, models in all_device_models(state, config, rng, noise).items()}
