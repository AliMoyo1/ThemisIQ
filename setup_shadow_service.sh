#!/bin/bash
# Sets up the shadow mode loop as a systemd service so it survives
# console disconnects, reboots, and session timeouts.

cat > /etc/systemd/system/themisiq-shadow.service << 'EOF'
[Unit]
Description=ThemisIQ Shadow Mode Loop
After=docker.service network.target
Requires=docker.service

[Service]
Type=simple
WorkingDirectory=/project
Environment="SECRET_KEY=shadow_temp_key"
Environment="DEBUG=true"
ExecStart=/usr/bin/python3 /project/oneforall/scripts/shadow_mode_loop.py \
    --sqlite /project/oneforall/data/oneforall.db \
    --postgres postgresql://themisiq:shadow_pass@localhost:5433/themisiq_shadow \
    --hours 48 --interval-hours 6
StandardOutput=append:/project/shadow.log
StandardError=append:/project/shadow.log
Restart=no

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl start themisiq-shadow
systemctl status themisiq-shadow
echo "Done. Check logs with: tail -5 /project/shadow.log"
