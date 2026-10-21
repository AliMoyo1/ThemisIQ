# 09 · Shadow AI and gateway feasibility

**Inspiration:** VerifyWise [Shadow AI tool discovery](https://verifywise.ai/user-guide/shadow-ai/ai-tools), [AI Gateway guardrails](https://verifywise.ai/user-guide/ai-gateway/guardrails), and [Agent Control](https://verifywise.ai/user-guide/ai-gateway/mcp-overview). **Priority:** later discovery, after governed inventory and monitoring. **Size:** discovery first; implementation TBD.

## Product question

Would ThemisIQ customers gain enough value from discovering unregistered AI tools or enforcing runtime AI controls to justify ingestion of network/model traffic, additional infrastructure, and support obligations? ThemisIQ currently has governance records, not assumed access to a customer's browser, proxy, SIEM, API gateway, or agent traffic. A dashboard without a real, consented signal source would create false confidence.

## Discovery slices

- **A (demand and data sources):** interview pilot organizations about shadow AI, approved AI tools, provider APIs, proxy/SIEM metadata, retention, residency, users/BU mapping, and who can act on findings. Require a named source system and owner; review whether aggregated tool usage is sufficient before individual-level data.
- **B (minimal opt-in pilot):** accept one agreed, structured feed of tool/provider, time bucket, organization, and coarse usage count. Deduplicate, classify “unreviewed/approved/restricted/blocked” as governance statuses, and link a reviewed tool to the canonical `applications` inventory. Show data freshness, coverage, uncertainty, and false-positive correction. Do not claim to detect all usage.
- **C (gateway option decision):** compare a read-only usage connector with a proxy that handles requests. If a proxy is justified, design separate service isolation, per-tenant keys, secret rotation, budgets, rate limits, explicit fail-open/fail-closed policy, logging minimization, latency SLO, incident path, and rollback. Agent tool-call approvals require exact tool scope and replay-safe decisions. Treat this as a separate product and operational approval gate, not a routine module page.

## Go/no-go gates

- At least one pilot has an authorized, maintainable data source and a clear action for each detected event; acceptable false-positive and coverage measures are agreed before displaying a risk score.
- A privacy and security review approves retained fields, identity granularity, retention, access, onward transfers, and customer controls. ThemisIQ can delete or expire events without corrupting canonical governance decisions.
- For any proxy, failure behavior, key isolation, throughput, support ownership, and provider billing are proven under realistic load before production traffic is routed through it.

**Out of scope until approved:** blanket employee monitoring, endpoint agents, full prompt/response capture, silent network scanning, and a production LLM/MCP proxy on the existing app service.
