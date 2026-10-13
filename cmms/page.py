"""The mock CMMS's one web page: a table of tickets, newest first. Standard library only, so it is tested without FastAPI."""
from html import escape

COLUMNS = (("id", "Ticket"), ("created_at", "Created (UTC)"), ("site", "Site"), ("equipment", "Equipment"),
           ("fault_started_at", "Fault started (UTC)"), ("priority", "Priority"), ("status", "Status"), ("summary", "Summary"))

STYLE = """
:root { color-scheme: light dark; }
body { font: 15px/1.5 system-ui, sans-serif; margin: 24px 16px; max-width: 1100px; }
h1 { font-size: 20px; margin: 0 0 4px; }
p { margin: 0 0 16px; opacity: .75; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid rgba(128, 128, 128, .35); }
th { font-weight: 600; }
.empty { padding: 24px 0; opacity: .75; }
"""


def render_page(tickets):
    head = "".join("<th>%s</th>" % escape(label) for _, label in COLUMNS)
    rows = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % escape(str(ticket[key])) for key, _ in COLUMNS) for ticket in tickets)
    body = "<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (head, rows) if tickets else \
        '<div class="empty">No tickets yet.</div>'
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, "
            "initial-scale=1\"><meta http-equiv=\"refresh\" content=\"5\"><title>Mock CMMS</title><style>%s</style></head><body>"
            "<h1>Mock CMMS: repair tickets</h1><p>A stand-in for a maintenance system. Simulated. Personal learning project. "
            "This page refreshes every 5 seconds.</p>%s</body></html>" % (STYLE, body))
