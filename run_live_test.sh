#!/bin/bash
# Live test - fills all fields, pauses before submit
cd /Users/blakeb/job-bot
echo "SKIP" | python3 scripts/auto_apply.py --jobs test_live_human_interest.json
