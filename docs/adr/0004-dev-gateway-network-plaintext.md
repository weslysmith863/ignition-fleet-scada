# ADR 0004: Plaintext Gateway Network for local development

Status: Accepted for development only (2026-10-01). Revisit before any shared or demo deployment.

## Context

The Gateway Network normally uses SSL (port 8060). In the Phase 0 spike, the site gateway's outgoing connection
to the hub failed the TLS handshake: the hub presents a self-signed certificate whose name is the container ID,
and the site had no approved certificate for it ("No approved certificate could be found in the certificates
folder"). Making this work requires an explicit certificate-trust step on the site gateway.

## Decision

- In local Docker Compose, the Gateway Network runs without SSL over the private Compose network
  (`GATEWAY_NETWORK_REQUIRESSL=false` on the hub; `GATEWAY_NETWORK_0_ENABLESSL=false` and port 8088 on the site).
- Authorization is still enforced: the hub uses the `SpecifiedList` security policy and only accepts `site1`.
- SSL with approved certificates is a documented follow-up (candidate for Phase 4 hardening or a stretch item).

## Also relaxed for local development: REST API key transport

The gateway setting "Require secure connections for API Keys" is **left unchecked** on the dev gateways
(2026-10-02). Our dev gateways are served over plain `http://localhost`, and with the setting enabled every
API call and the API Keys page itself would return 403. API tokens therefore travel unencrypted on this PC.
For any shared or real deployment, enable the setting and serve the gateway over HTTPS.

## Consequences

- The link carries traffic unencrypted. Acceptable only because both gateways are containers on a private
  network on one developer PC. Never expose this configuration beyond localhost.
- Teach-back topic: why real fleets use SSL plus certificate approval, and what "two-way auth" adds.
