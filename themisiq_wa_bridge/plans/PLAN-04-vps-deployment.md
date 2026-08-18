# PLAN-04: Deploy the Bridge to the VPS (systemd + nginx + Cloudflare + Meta)

PREREQUISITE: PLAN-01, PLAN-02, PLAN-03 complete. PLAN-05 sign-offs must be complete BEFORE the final go-live step (Step 10).

## Goal

Run the bridge as a hardened service on the same VPS as ThemisIQ (which already runs `themisiq-app.service` behind nginx + Cloudflare), reachable at `https://bridge.themisiq.net`, wired to Meta's WhatsApp Cloud API and to a ThemisIQ webhook.

## Files/resources to touch

- VPS: `/opt/themisiq-bridge/` (new directory), `/etc/systemd/system/themisiq-bridge.service` (new), `/etc/nginx/sites-available/themisiq-bridge` (new), `/etc/logrotate.d/themisiq-bridge` (new)
- Cloudflare DNS: new `bridge` A record
- Meta developer console: app webhook configuration
- ThemisIQ admin UI: API key + webhook creation

## Rules for every terminal step

The operator types commands manually into the Hetzner console. Therefore every step below is ONE single copy-pasteable command. Never bundle two commands with `&&` or a semicolon. Never use a pipe character in any command.

## Steps in order

### Step 1: Create the service user and directory

Run each line as its own step:

```
sudo useradd --system --create-home --shell /usr/sbin/nologin themisbridge
```

```
sudo mkdir -p /opt/themisiq-bridge
```

```
sudo chown themisbridge:themisbridge /opt/themisiq-bridge
```

### Step 2: Get the code onto the VPS

If the bridge is in the main git repo, clone or pull it the same way `themisiq-app` is deployed today. Otherwise copy from the workstation (run this ON THE WORKSTATION, one command):

```
scp -r "C:\Projects\One For All\One For All\themisiq_wa_bridge" root@YOUR_VPS_IP:/opt/themisiq-bridge/app-src
```

Then on the VPS:

```
sudo chown -R themisbridge:themisbridge /opt/themisiq-bridge
```

Note: the `__pycache__` folders and any local `audit.log.jsonl`, `tenant_map.json`, `.env` from the workstation must NOT be copied. Delete them on the VPS if they arrived:

```
sudo rm -rf /opt/themisiq-bridge/app-src/app/__pycache__
```

```
sudo rm -f /opt/themisiq-bridge/app-src/audit.log.jsonl
```

```
sudo rm -f /opt/themisiq-bridge/app-src/.env
```

```
sudo rm -f /opt/themisiq-bridge/app-src/tenant_map.json
```

### Step 3: Python environment

```
sudo -u themisbridge python3 -m venv /opt/themisiq-bridge/venv
```

```
sudo -u themisbridge /opt/themisiq-bridge/venv/bin/pip install -r /opt/themisiq-bridge/app-src/requirements.txt
```

```
sudo -u themisbridge /opt/themisiq-bridge/venv/bin/pip install uvicorn
```

### Step 4: Configuration files

Create the env file:

```
sudo -u themisbridge nano /opt/themisiq-bridge/app-src/.env
```

Paste this content, filling real values (get `WA_APP_SECRET` from Meta app settings, `WA_TOKEN` and `WA_PHONE_NUMBER_ID` from the WhatsApp product page, and invent a long random `WA_VERIFY_TOKEN`):

```
OFFLINE_MODE=false
BRIDGE_BASE_URL=https://bridge.themisiq.net
THEMIS_BASE_URL=https://themisiq.net
THEMIS_WEBHOOK_SECRET=REPLACE_LONG_RANDOM
WA_PROVIDER=meta
WA_VERIFY_TOKEN=REPLACE_LONG_RANDOM
WA_APP_SECRET=REPLACE_FROM_META
WA_TOKEN=REPLACE_FROM_META
WA_PHONE_NUMBER_ID=REPLACE_FROM_META
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=REPLACE
AI_MODEL=claude-opus-4-8
RATE_LIMIT_PER_USER_PER_MIN=10
```

Then lock permissions:

```
sudo chmod 600 /opt/themisiq-bridge/app-src/.env
```

Create the tenant map (first create the ThemisIQ API key: ThemisIQ admin, Command Centre, Developer, API Keys, create a key with ONLY the modules the pilot user needs ticked, copy it now because it is shown once):

```
sudo -u themisbridge nano /opt/themisiq-bridge/app-src/tenant_map.json
```

Content shape (wa id is the phone number with country code, no plus sign):

```
{
  "2637XXXXXXXX": {
    "tenant_id": "org_acme",
    "org_slug": "acme",
    "api_key": "PASTE_SCOPED_READONLY_KEY",
    "role": "compliance_manager",
    "modules": ["sentinel", "erm", "command_centre"],
    "alerts": ["sentinel.breach.confirmed", "sentinel.dsr.overdue", "erm.appetite.breached"]
  }
}
```

```
sudo chmod 600 /opt/themisiq-bridge/app-src/tenant_map.json
```

### Step 5: systemd unit

```
sudo nano /etc/systemd/system/themisiq-bridge.service
```

Content:

```
[Unit]
Description=ThemisIQ WhatsApp Bridge
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=themisbridge
Group=themisbridge
WorkingDirectory=/opt/themisiq-bridge/app-src
ExecStart=/opt/themisiq-bridge/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8090
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/opt/themisiq-bridge/app-src
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Then, one command per step:

```
sudo systemctl daemon-reload
```

```
sudo systemctl enable themisiq-bridge
```

```
sudo systemctl start themisiq-bridge
```

```
sudo systemctl status themisiq-bridge
```

```
curl http://127.0.0.1:8090/health
```

### Step 6: nginx server block

```
sudo nano /etc/nginx/sites-available/themisiq-bridge
```

Content (mirror the TLS certificate paths used by the existing themisiq.net server block; check that file first with `sudo cat /etc/nginx/sites-enabled/themisiq` or the equivalent name):

```
server {
    listen 443 ssl;
    server_name bridge.themisiq.net;

    ssl_certificate     /etc/ssl/SAME_AS_MAIN_SITE.pem;
    ssl_certificate_key /etc/ssl/SAME_AS_MAIN_SITE.key;

    client_max_body_size 1m;

    location / {
        proxy_pass http://127.0.0.1:8090;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 75s;
    }
}
```

```
sudo ln -s /etc/nginx/sites-available/themisiq-bridge /etc/nginx/sites-enabled/themisiq-bridge
```

```
sudo nginx -t
```

```
sudo systemctl reload nginx
```

### Step 7: Cloudflare DNS

In the Cloudflare dashboard for themisiq.net: add an A record, name `bridge`, value = the VPS IP, proxy status Proxied (orange cloud). If the site uses a Cloudflare origin certificate, the same certificate covers `bridge.themisiq.net` only if it was issued with a wildcard; verify, otherwise issue a new origin cert including the subdomain.

Verify from the workstation:

```
curl https://bridge.themisiq.net/health
```

### Step 8: Log rotation for the audit file

```
sudo nano /etc/logrotate.d/themisiq-bridge
```

Content (rotation keeps the file bounded; the 7-year retention copy is the rotated archives, do not delete them):

```
/opt/themisiq-bridge/app-src/audit.log.jsonl {
    monthly
    rotate 84
    compress
    missingok
    notifempty
    copytruncate
}
```

### Step 9: Wire ThemisIQ webhook (proactive alerts)

In ThemisIQ admin: Command Centre, Developer, Webhooks, create a webhook with URL `https://bridge.themisiq.net/webhook/themisiq`, events `webhook.test,sentinel.breach.confirmed,sentinel.dsr.overdue,erm.appetite.breached`, and copy the generated secret into the bridge `.env` as `THEMIS_WEBHOOK_SECRET` (then restart):

```
sudo systemctl restart themisiq-bridge
```

Click the webhook Test button in ThemisIQ and confirm the pilot WhatsApp number receives the test message.

### Step 10: Meta webhook go-live (GATED on PLAN-05 sign-offs)

Only after the PLAN-05 checklist is fully signed off:

1. In the Meta developer console, WhatsApp product, Configuration: set Callback URL `https://bridge.themisiq.net/webhook/whatsapp`, Verify token = the `WA_VERIFY_TOKEN` value. Click Verify and Save (this calls the GET handshake).
2. Subscribe to the `messages` webhook field only.
3. From the pilot phone, send `help` to the business number and confirm the reply plus the privacy notice arrive.

## Edge cases a weaker model would miss

1. **One command per step is a hard rule for this operator** (manual typing into the Hetzner console). No `&&`, no semicolons chaining commands, no pipe characters anywhere in commands.
2. **Bind uvicorn to 127.0.0.1**, not 0.0.0.0. Only nginx (and through it Cloudflare) may reach the bridge. Exposing 8090 publicly bypasses Cloudflare's WAF and TLS.
3. **`ProtectSystem=strict` needs `ReadWritePaths`** for the app dir, or the audit log and seen_intro.json writes fail silently at runtime with read-only filesystem errors.
4. **Meta requires the GET verification handshake to succeed before it will save the callback URL.** The service, nginx, and DNS must all be live BEFORE Step 10. Verify order matters.
5. **Cloudflare proxying is fine for Meta webhooks** (Meta publishes no fixed IPs to allowlist), but if Cloudflare "Bot Fight Mode" or a WAF rule challenges Meta's POSTs, deliveries fail silently. If verified messages never arrive, check Cloudflare Firewall Events first and add a WAF skip rule for `bridge.themisiq.net/webhook/*`.
6. **Do not put secrets in the systemd unit or nginx config.** The unit reads nothing secret; the app loads `.env` from its working directory (pydantic settings). File mode 600 on `.env` and `tenant_map.json`.
7. **The API key is shown once** in ThemisIQ. Create it and paste it into `tenant_map.json` in the same sitting.
8. **`copytruncate` in logrotate** because the bridge keeps the file handle open per write call; plain rotation with create is also safe here (the code re-opens per write), but copytruncate avoids any race either way.
9. **Restart the bridge after every `.env` or `tenant_map.json` change.** The tenant map loads at startup only.
10. **Wildcard vs exact certificate:** a Cloudflare origin cert for `themisiq.net` without `*.themisiq.net` makes nginx serve a mismatched cert to Cloudflare and the tunnel fails with 526 errors. Check before Step 7.
11. **The pilot user's WhatsApp id format:** country code + number, digits only (for example `263783047375`), because that is what Meta puts in `contacts[0].wa_id`. A leading plus sign in the map means the lookup silently misses and every message answers "not linked".
12. **Firewall:** if ufw is active, no new port needs opening (443 is already open for nginx; 8090 stays internal). Do not open 8090.

## Acceptance criteria (verify each)

1. `sudo systemctl status themisiq-bridge` shows active (running), and survives `sudo reboot` (comes back enabled).
2. `curl http://127.0.0.1:8090/health` on the VPS returns `{"status":"ok",...}`.
3. `curl https://bridge.themisiq.net/health` from outside returns the same through Cloudflare.
4. `curl http://YOUR_VPS_IP:8090/health` from outside FAILS (connection refused/timeout), proving the loopback bind.
5. Meta's Verify and Save succeeds (handshake 200 with the challenge echoed).
6. Sending `help` from the pilot phone returns the help menu; first contact also shows the privacy notice.
7. `list open DSRs` returns real tenant data; a module the user lacks returns the access-denied message.
8. ThemisIQ webhook Test button delivers a WhatsApp message to the pilot phone within seconds, and the webhook's delivery log in ThemisIQ shows success=1.
9. `sudo -u themisbridge cat /opt/themisiq-bridge/app-src/audit.log.jsonl` shows one JSON line per interaction with actor, tenant, action, ok.
10. `.env` and `tenant_map.json` are mode 600 owned by themisbridge, and neither exists in any git repository.
11. An unsigned POST to `https://bridge.themisiq.net/webhook/whatsapp` returns 401 or 503, never 200 processing.
