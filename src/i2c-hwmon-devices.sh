#!/bin/bash
set -euo pipefail
bus="${I2C_BUS:-0}"; lm75="${LM75_ADDR:-0x4a}"; tc654="${TC654_ADDR:-0x1b}"
[[ "$bus" =~ ^[0-9]+$ ]] || { echo 'Invalid I2C bus' >&2; exit 1; }
[[ "$lm75" =~ ^0x[0-9a-fA-F]{2}$ && "$tc654" =~ ^0x[0-9a-fA-F]{2}$ ]] || { echo 'Invalid I2C address' >&2; exit 1; }
modprobe lm75; modprobe tc654; modprobe coretemp
for _ in {1..20}; do [ -e "/sys/bus/i2c/devices/i2c-$bus/new_device" ] && break; sleep 1; done
new="/sys/bus/i2c/devices/i2c-$bus/new_device"
[ -e "$new" ] || { echo "I2C bus $bus unavailable" >&2; exit 1; }
bind_device() {
  local driver="$1" address="$2" address_id device
  printf -v address_id '%04x' "$((address))"
  device="/sys/bus/i2c/devices/$bus-$address_id"
  if [ ! -e "$device/name" ]; then echo "$driver $address" > "$new"; fi
  [ "$(cat "$device/name")" = "$driver" ] || { echo "Wrong device bound at $device" >&2; return 1; }
}
bind_device lm75 "$lm75"
bind_device tc654 "$tc654"
