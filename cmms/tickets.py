"""The mock CMMS's ticket store (ADR 0019): SQLite behind a small class, standard library only.

A CMMS (computerized maintenance management system) is where repair work is tracked. This one is a stand-in that accepts
tickets over HTTP from the site gateways' Event Streams. It keeps its own file and not the fleet database, as a real
maintenance system would.

One ticket per fault. The key is (site, equipment, fault_started_at), so a request that arrives twice, for example because the
sender retried after a timeout, creates the ticket once and answers with the existing one. The start time is normalized to UTC
first, so the same instant sent as epoch milliseconds or as an ISO-8601 string is the same fault.
"""
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

PRIORITIES = ("Diagnostic", "Low", "Medium", "High", "Critical")  # the scheme of decision D70
DEFAULT_PRIORITY = "High"
MAX_TEXT = 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at       TEXT NOT NULL,
    site             TEXT NOT NULL,
    equipment        TEXT NOT NULL,
    fault_started_at TEXT NOT NULL,
    priority         TEXT NOT NULL,
    summary          TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'open',
    UNIQUE (site, equipment, fault_started_at)
);
"""

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


class TicketError(ValueError):
    """A request the store refuses. The message says what was wrong, and is sent back to the caller."""


def normalize_time(value):
    """A start time as UTC ISO-8601 with milliseconds and a Z. Accepts epoch milliseconds (a number or digits in a string) or
    an ISO-8601 string that carries a time zone; a time with no zone is refused because it could mean two different instants."""
    if value is None or isinstance(value, bool):
        raise TicketError("fault_started_at is required: epoch milliseconds or an ISO-8601 time with a time zone")
    if isinstance(value, str):
        text = value.strip()
        if _NUMBER.match(text):
            value = float(text)
        else:
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError:
                raise TicketError("fault_started_at %r is not epoch milliseconds or an ISO-8601 time" % value)
            if parsed.tzinfo is None:
                raise TicketError("fault_started_at %r has no time zone; add Z or an offset such as -05:00" % value)
            return _format(parsed.astimezone(timezone.utc))
    if isinstance(value, (int, float)):
        try:
            return _format(_EPOCH + timedelta(milliseconds=int(round(value))))
        except OverflowError:
            raise TicketError("fault_started_at %r is out of range" % value)
    raise TicketError("fault_started_at must be a number or a string")


def _format(moment):
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _text(payload, field, default=None):
    value = payload.get(field)
    if value is None and default is not None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise TicketError("%s is required and must be text" % field)
    value = value.strip()
    if len(value) > MAX_TEXT:
        raise TicketError("%s is longer than %d characters" % (field, MAX_TEXT))
    return value


class TicketStore:
    def __init__(self, path=":memory:", clock=None):
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()  # the web server answers on several threads; one connection is shared
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            self._db.executescript(SCHEMA)

    def create(self, payload):
        """Make the ticket, or find the one that already exists. Returns (ticket, created) with created False for a repeat."""
        if not isinstance(payload, dict):
            raise TicketError("the request body must be a JSON object")
        site = _text(payload, "site")
        equipment = _text(payload, "equipment")
        started = normalize_time(payload.get("fault_started_at"))
        priority = payload.get("priority", DEFAULT_PRIORITY)
        if priority not in PRIORITIES:
            raise TicketError("priority %r is not one of %s" % (priority, ", ".join(PRIORITIES)))
        summary = _text(payload, "summary", default="Fault on %s %s" % (site, equipment))
        key = (site, equipment, started)
        find = "SELECT * FROM tickets WHERE site = ? AND equipment = ? AND fault_started_at = ?"
        with self._lock, self._db:
            # Look first and insert only when the fault is new: an INSERT that is ignored as a duplicate still uses up a ticket
            # number in SQLite, which would leave gaps in the numbers after every retry. The UNIQUE constraint stays as the
            # backstop for a second process.
            row = self._db.execute(find, key).fetchone()
            if row is not None:
                return dict(row), False
            try:
                self._db.execute(
                    "INSERT INTO tickets (created_at, site, equipment, fault_started_at, priority, summary) VALUES (?, ?, ?, ?, ?, ?)",
                    (_format(self._clock()), site, equipment, started, priority, summary))
            except sqlite3.IntegrityError:
                return dict(self._db.execute(find, key).fetchone()), False
            return dict(self._db.execute(find, key).fetchone()), True

    def get(self, ticket_id):
        with self._lock:
            row = self._db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        return dict(row) if row else None

    def list(self):
        """Every ticket, newest first."""
        with self._lock:
            return [dict(row) for row in self._db.execute("SELECT * FROM tickets ORDER BY id DESC")]

    def count(self):
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]

    def close(self):
        with self._lock:
            self._db.close()
