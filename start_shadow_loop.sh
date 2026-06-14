#!/bin/bash
cd /project
export SECRET_KEY=shadow_temp_key
export DEBUG=true
nohup python3 oneforall/scripts/shadow_mode_loop.py \
    --sqlite oneforall/data/oneforall.db \
    --postgres "postgresql://themisiq:shadow_pass@localhost:5433/themisiq_shadow" \
    --hours 48 --interval-hours 6 \
    >> /project/shadow.log 2>&1 &
echo "Shadow loop PID: $!"
