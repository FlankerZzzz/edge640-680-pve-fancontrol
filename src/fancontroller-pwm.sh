#!/bin/bash
set -euo pipefail
# Python tick and Web writes share /run/fancontroller-pwm.lock internally.
exec /usr/bin/python3 /usr/local/lib/edge-fancontrol/fancontrol.py tick
