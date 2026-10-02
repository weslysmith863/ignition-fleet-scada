# ADR 0005: Deploy and configure gateways through the REST API

Status: Accepted (2026-10-02), based on Phase 0 spikes against Ignition 8.3.9 Maker in Docker.

## Context

Git is the source of truth for projects and configuration, so something must move files from the repo into
running gateways and back. Two natural approaches were tried:

1. **Bind-mount the repo folder** into the gateway container. Findings: it loads at startup, but (a) on a
   brand-new data volume Docker creates `projects/` as root and the gateway faults with AccessDenied,
   (b) the running gateway does not notice edits made on the Windows side, and (c) it depends on file-system
   behavior that differs between Windows, WSL, and Linux.
2. **Use the gateway's REST API** (OpenAPI spec served at `/openapi.json`, authenticated with an API key sent as
   `X-Ignition-API-Token`).

## What the spikes proved (site1, 2026-10-02)

| Need | Mechanism | Result |
|---|---|---|
| Deploy a project from the repo | zip the folder, `POST /data/api/v1/projects/import/{name}` (`overwrite=true` to update) | works, project starts within a second |
| Export a project to the repo | `GET /data/api/v1/projects/export/{name}` returns a zip with the same layout as the repo folder | works |
| Alternative: copy files then reload | `docker cp` plus `POST /data/api/v1/scan/projects` (and `/scan/config`) | works; an in-place edit was picked up after the scan |
| Create and update tags and UDTs | `POST /data/api/v1/tags/import` (json/xml/csv, collision policy, target path); `GET /tags/export` | works |
| Create gateway resources (database connections, devices, historian providers, tag providers, security levels, secret providers, gateway network, and more) | `POST /data/api/v1/resources/{module}/{type}` with an array body | works (database connection, SQL and Core historian providers created) |
| Pass secrets without committing them | `POST /data/api/v1/encryption/encrypt` turns a plain value into an embedded secret; or a `file` secret provider | works |

## Decision

- The deploy and admin tooling talks to each gateway through the REST API. It does not rely on bind-mounted
  project folders or file watching.
- **Projects:** the repo holds the project folders. `deploy` zips them and imports with overwrite; `export`
  pulls the zip and unpacks it into the repo so Designer edits show up as a normal Git diff.
- **Tags, UDTs, devices, connections, historians, alarm and security resources:** generated from the points-list
  CSV and applied through `tags/import` and `resources/*`.
- **Secrets** live only in the gitignored `.env`. The tooling encrypts them on the target gateway at deploy time.
- `scan/projects` and `scan/config` remain the fallback for bulk file-level changes.
- Each gateway has its own API key. The key needs a custom security level (built-in roles cannot be assigned to
  API keys in 8.3) and the gateway's Gateway Write Permissions setting must allow that level.

## Consequences

- Deployment is explicit and repeatable, and does not depend on the host operating system's file semantics.
- `resource.json` files carry a modification signature and timestamp that change on every save, so diffs are noisy
  and concurrent edits to one resource will conflict.
- A volume wipe (`down -v`) leaves a leased Maker license held; regenerate that license's token before restart.
- DNP3 is not offered as a device type on the Maker gateway, so DNP3 remains out of scope.
