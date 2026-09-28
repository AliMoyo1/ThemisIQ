# Outbound webhook/connector egress: operator guide

Status as of 2026-09-24: application-layer hardening built and tested
(PLAN-36 T05, findings.md F06 + F07). This document is for whoever operates
the app on the Hetzner VPS (`themisiq-app.service`), not for application
developers -- it covers the one mitigation this task's code changes cannot
provide on their own: a network-layer egress rule.

## 1. What the application layer already does

Every outbound call the app makes to an admin-entered destination (generic
webhooks, Slack, Teams, WhatsApp -- save, test-send, and real event
delivery) goes through `core/outbound_http.py`:

- `validate_outbound_url()`: requires `https://`, rejects embedded
  credentials, resolves every A/AAAA record for the hostname, and rejects
  the destination outright if *any* resolved address is loopback,
  RFC1918/ULA private, link-local (this is the range that includes the
  `169.254.169.254` cloud metadata address), reserved, multicast, or
  unspecified.
- `send_outbound()`: revalidates immediately before connecting (a URL
  checked at save time can resolve somewhere else by send time), applies
  strict per-phase timeouts, never follows redirects, and caps the response
  body it reads back.

This closes the main application-level gap (PLAN-36 finding F07: the old
code matched IP ranges by string prefix and missed most of
`172.16.0.0/12`, never checked IPv6, and followed redirects). See that
file's own module docstring for the full policy.

## 2. The residual risk this cannot close: DNS rebinding

`validate_outbound_url()`'s DNS lookup and the connection `send_outbound()`
opens a moment later are two separate resolutions. Between them, an
attacker who controls the destination's DNS can rebind the hostname from a
public address to an internal one. There is no portable way in Python to
force httpx's TLS connection to the exact IP already resolved without
reimplementing HTTP/TLS by hand, so this module cannot close that window by
itself -- it must be paired with a network-layer control that does not
depend on which IP the application resolved.

## 3. Required production mitigation: block the ranges at the network layer

On the VPS, restrict the `themisiq-app.service` process's own outbound
traffic so that even a successfully rebound connection cannot reach
anything internal. This is independent of and does not replace the
application-layer checks above -- it is the backstop for the one gap they
cannot close.

Recommended approach (nftables, run as root, adjust the service's runtime
user if it is not the default):

```
# Block the app's outbound traffic to private/link-local/metadata ranges.
# Public HTTPS destinations (the only thing webhooks/connectors ever need)
# are unaffected.
nft add table inet themisiq_egress
nft add chain inet themisiq_egress output '{ type filter hook output priority 0 ; policy accept ; }'
nft add rule inet themisiq_egress output meta skuid themisiq daddr { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16, 127.0.0.0/8 } reject
```

Points that matter when adapting this:

- Scope the rule to the service's actual runtime UID (`meta skuid`), not
  the whole host, so the VPS's own outbound traffic (package updates,
  PostgreSQL if remote, etc.) is unaffected.
- Include `169.254.169.254` via the `169.254.0.0/16` block -- this is the
  cloud-metadata address range on most providers and the single
  highest-value SSRF target.
- If the app ever needs to reach a legitimate internal service (e.g. a
  self-hosted PostgreSQL on a private network) as part of normal
  operation, that destination needs an explicit `accept` rule placed
  *before* the reject rule above, not a loosening of the reject rule
  itself.
- A forward proxy with an explicit allowlist is an equally valid
  alternative to host firewall rules and is preferable if the app is ever
  split across multiple hosts; the goal (only public HTTPS destinations
  reachable) is what matters, not the specific mechanism.

This rule is not applied by any script in this repository and must be set
up manually on the VPS -- deploying it is a separate, explicit operational
step, not something PLAN-36's code changes do for you.

## 4. Where this is tested

`oneforall/tests/test_outbound_http.py`, `tests/test_webhooks.py`,
`tests/test_notifications.py`, and `tests/test_webhook_test_endpoint.py`
cover the application-layer policy (DNS classification, redirect/timeout/
response-cap behavior, and that Slack/Teams/WhatsApp/generic webhooks all
share it). None of them can exercise the network-layer rule in this
section, since that rule does not exist anywhere but the target VPS.
