"""Read and check the points list: one row per device (decision D9). Standard library only."""
import csv
import re
from dataclasses import dataclass

COLUMNS = ("site", "device", "kind", "unit_id", "host", "port", "rated_kw")
# Each kind of device maps to a UDT and the tag folder its instances live in (ADR 0007); an empty folder means the tag
# root (Weather and Meter). Only an inverter has a rating: rated_kw is required for it and must stay empty for the rest.
KINDS = {
    "inverter": {"udt": "Inverter", "folder": "Inverters", "rated": True},
    "weather": {"udt": "Weather", "folder": "", "rated": False},
    "meter": {"udt": "Meter", "folder": "", "rated": False},
}
NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


class PointsError(ValueError):
    pass


@dataclass(frozen=True)
class DeviceRow:
    site: str
    device: str
    kind: str
    unit_id: int
    host: str
    port: int
    rated_kw: float | None  # None for a kind without a rating

    @property
    def udt(self):
        return KINDS[self.kind]["udt"]

    @property
    def folder(self):
        return KINDS[self.kind]["folder"]

    @property
    def tag_path(self):
        """Where the instance lives in the default tag provider, e.g. Inverters/Inv1 or Weather."""
        return "%s/%s" % (self.folder, self.device) if self.folder else self.device


def read_points(path):
    """Rows of the points list, checked. Raises PointsError with the line number of the first problem."""
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise PointsError("header must be exactly: %s" % ",".join(COLUMNS))
        rows = [_parse(line, number) for number, line in enumerate(reader, start=2)]
    _check_unique(rows)
    return rows


def _parse(line, number):
    def fail(message):
        raise PointsError("line %d: %s" % (number, message))

    for column in COLUMNS:
        if column != "rated_kw" and not (line[column] or "").strip():
            fail("%s is empty" % column)
    site, device, kind, host = (line[c].strip() for c in ("site", "device", "kind", "host"))
    if not NAME.match(site):
        fail("site %r is not a plain name" % site)
    if not NAME.match(device):
        fail("device %r is not a plain name (letters, digits, underscore; starts with a letter)" % device)
    if kind not in KINDS:
        fail("kind %r is not one of %s" % (kind, sorted(KINDS)))
    try:
        unit_id, port = int(line["unit_id"]), int(line["port"])
    except ValueError:
        fail("unit_id and port must be whole numbers")
    if not 1 <= unit_id <= 247:
        fail("unit_id %d is outside 1 to 247 (the usual Modbus range)" % unit_id)
    if not 1 <= port <= 65535:
        fail("port %d is outside 1 to 65535" % port)
    rated_text = (line["rated_kw"] or "").strip()
    if KINDS[kind]["rated"]:
        try:
            rated_kw = float(rated_text)
        except ValueError:
            fail("rated_kw must be a number (kind %s needs a rating)" % kind)
        if rated_kw <= 0:
            fail("rated_kw must be positive")
    else:
        if rated_text:
            fail("rated_kw must be empty for kind %s (only an inverter has a rating)" % kind)
        rated_kw = None
    return DeviceRow(site, device, kind, unit_id, host, port, rated_kw)


def _check_unique(rows):
    names, addresses = {}, {}
    for row in rows:
        key = (row.site, row.device)
        if key in names:
            raise PointsError("device %s appears twice on site %s" % (row.device, row.site))
        names[key] = row
        address = (row.site, row.host, row.port, row.unit_id)
        if address in addresses:
            raise PointsError("%s and %s use the same host, port, and unit ID" % (addresses[address].device, row.device))
        addresses[address] = row
