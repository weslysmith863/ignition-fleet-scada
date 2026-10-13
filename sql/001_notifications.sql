-- Escalation notifications. An alarm pipeline on a site gateway writes one row here when an alarm has gone unacknowledged
-- long enough (a stand-in for an email or pager; ADR 0018 once the pipeline is settled). The table is ours, so unlike the
-- alarm journal's tables it carries a site column and every gateway writes to the same one. event_id is the alarm event's
-- id, the same value as the journal's eventid, so a notification joins to its alarm's journal rows.
-- Safe to run more than once. Apply with:
--   docker.exe compose exec -T postgres psql -U fleet -d fleet -v ON_ERROR_STOP=1 -f - < sql/001_notifications.sql
CREATE TABLE IF NOT EXISTS notifications (
    id         bigserial PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    site       text NOT NULL,
    event_id   text NOT NULL,
    source     text NOT NULL,
    priority   text NOT NULL,
    reason     text NOT NULL,
    message    text
);

CREATE INDEX IF NOT EXISTS notifications_event_id_idx ON notifications (event_id);
