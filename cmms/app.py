"""The mock CMMS as a web service (ADR 0019): FastAPI around the ticket store.

    POST /tickets      create a ticket (201), or answer with the existing one for a repeated fault (200)
    GET  /tickets      every ticket, newest first, as JSON
    GET  /tickets/{id} one ticket
    GET  /             the same list as a web page for a person
    GET  /health       the container's health check

The request body is read as JSON whatever Content-Type the sender declares, so a sender that forgets the header still works.
FastAPI's own interactive page is at /docs.
"""
import json
import logging
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from cmms.page import render_page
from cmms.tickets import TicketError, TicketStore

log = logging.getLogger("uvicorn.error")  # shares uvicorn's handler, so these lines appear in `docker compose logs cmms`
store = TicketStore(os.environ.get("CMMS_DB", "/data/cmms.sqlite3"))

app = FastAPI(title="Mock CMMS", description="A stand-in maintenance system for the fleet SCADA project. Simulated.")

TICKET_BODY = {"requestBody": {"required": True, "content": {"application/json": {"example": {
    "site": "site1", "equipment": "Inv1", "fault_started_at": "2026-10-13T18:34:47.476Z", "priority": "High",
    "summary": "Inverter fault"}}}}}


@app.get("/health")
def health():
    return {"status": "ok", "tickets": store.count()}


@app.post("/tickets", openapi_extra=TICKET_BODY)
async def create_ticket(request: Request):
    try:
        payload = json.loads(await request.body())
    except ValueError:
        raise HTTPException(status_code=400, detail="the body is not valid JSON")
    try:
        ticket, created = store.create(payload)
    except TicketError as error:
        log.warning("ticket refused: %s", error)
        raise HTTPException(status_code=422, detail=str(error))
    log.info("ticket %d %s: %s %s fault at %s", ticket["id"], "created" if created else "already existed (duplicate ignored)",
             ticket["site"], ticket["equipment"], ticket["fault_started_at"])
    return JSONResponse({"created": created, "ticket": ticket}, status_code=201 if created else 200)


@app.get("/tickets")
def list_tickets():
    return store.list()


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: int):
    ticket = store.get(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="no such ticket")
    return ticket


@app.get("/", response_class=HTMLResponse)
def page():
    return render_page(store.list())
