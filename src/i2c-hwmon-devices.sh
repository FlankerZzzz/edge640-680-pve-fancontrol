#!/bin/bash
set -euo pipefail
bus="${I2C_BUS:-0}"; lm75="${LM75_ADDR:-0x4a}"; tc654="${TC654_ADDR:-0x1b}"
modprobe lm75; modprobe tc654
for _ in {1..20}; do [ -e "/sys/bus/i2c/devices/i2c-$bus/new_device" ] && break; sleep 1; done
new="/sys/bus/i2c/devices/i2c-$bus/new_device"
[ -e "$new" ] || { echo "I2C bus $bus unavailable" >&2; exit 1; }
grep -q "lm75" /sys/bus/i2c/devices/*/name 2>/dev/null || echo "lm75 $lm75" > "$new" || true
grep -q "tc654" /sys/bus/i2c/devices/*/name 2>/dev/null || echo "tc654 $tc654" > "$new" || true
