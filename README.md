# Water Meter — Home Assistant Integration

A Home Assistant custom integration for a locally hosted water meter that exposes a [Prometheus exposition format](https://prometheus.io/docs/instrumenting/exposition_formats/) endpoint. Provides real-time flow rate, daily usage, and a cumulative lifetime total compatible with the [Energy Dashboard](https://www.home-assistant.io/docs/energy/water/).

## Sensors

| Entity | Name | Unit | Description |
|--------|------|------|-------------|
| `sensor.water_usage_today` | Water Usage Today | L | Litres used since midnight. Resets at midnight (HA timezone). Survives device reboots — if the meter resets mid-day, usage is accumulated on top of the existing total. |
| `sensor.water_flow_rate` | Water Flow Rate | L/min | Current flow rate |
| `sensor.water_lifetime_total` | Water Lifetime Total | L | Cumulative total, never resets — use this for the Energy Dashboard |

## Requirements

A water meter device that serves [Prometheus exposition format](https://prometheus.io/docs/instrumenting/exposition_formats/) metrics at its root HTTP endpoint. The device must respond to `GET http://<device-ip>/` with plain text in the following format:

```
# HELP water_today_litres Total litres of water used since midnight.
# TYPE water_today_litres counter
water_today_litres 0.00
# HELP water_flowrate_lpm Current flowrate in litres per minute.
# TYPE water_flowrate_lpm gauge
water_flowrate_lpm 0.00
```

For example - https://gist.github.com/Tugzrida/2c9fcf52571909cf60cbafc32413daf0 by [Cameron / Tugzrida](https://tugzrida.xyz)

## Installation

### HACS (recommended)

1. In Home Assistant, open HACS
2. Click the three-dot menu → **Custom repositories**
3. Add `https://github.com/BeauGiles/ha-water-meter` with category **Integration**
4. Click **Download**
5. Restart Home Assistant

### Manual

1. Copy `custom_components/water_meter/` into your HA config directory under `custom_components/`
2. Restart Home Assistant

## Setup

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Water Meter**
3. Enter your device's IP address and polling interval (default: 4 seconds)
4. Click **Submit** — HA will verify the connection before saving

To change the IP or polling interval later, use the **··· → Reconfigure** menu on the integration card.

## Energy Dashboard

Add `sensor.water_lifetime_total` to the Energy Dashboard under **Settings → Energy → Water → Add water source**.

This sensor accumulates usage across midnight rollovers and HA restarts and never resets, making it the correct source for long-term statistics.

## Troubleshooting

- Confirm the device is reachable: `curl http://<device-ip>/`
- Check HA logs under **Settings → System → Logs**, filter for `water_meter`
- Midnight resets use HA's configured timezone (Settings → System → General) — make sure this is set correctly for your location
