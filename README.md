# Bluetti Cloud — Home Assistant Integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/thierrycoopman/battery-ha)](https://github.com/thierrycoopman/battery-ha/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A custom Home Assistant integration that connects to Bluetti power stations via the Bluetti Cloud mobile app API. This integration supports devices that are **not covered** by the official Bluetti HA integration (e.g., AC300, AC200, and other older models).

## Why This Integration?

The official Bluetti HA integration uses OAuth2 and the `/ha/v1/` API namespace, which only supports newer device models. Older devices like the AC300 show as "offline" even when they're fully operational in the Bluetti mobile app.

This integration uses the same API as the Bluetti mobile app, providing full access to device telemetry and control for all cloud-connected Bluetti devices.

## Features

- **Real-time MQTT telemetry** — Battery SOC, pack voltage/current, charging status updated in ~1 second via MQTT push
- **REST API fallback** — Power readings, energy totals, and online status polled every 60s (30s if MQTT unavailable)
- **AC/DC control** — Switch entities to toggle AC and DC outputs via MQTT with optimistic state updates
- **Power monitoring** — PV input, grid input, AC output, DC output, grid feed-in (in Watts)
- **Energy tracking** — Daily, monthly, yearly, and lifetime energy totals (kWh) for the HA Energy Dashboard
- **Online status** — Binary sensor showing device connectivity
- **Multi-device support** — Monitor and control multiple Bluetti devices
- **Graceful degradation** — If MQTT is unavailable, the integration falls back to REST-only polling

### Architecture

```
                          ┌──────────────┐
  MQTT (real-time ~1s)    │              │    REST API (every 60s)
  PUB/{model}/{subSn} ──> │  Coordinator  │ <── homeDevices + lastAlive + energyDetail
  Modbus RTU frames       │              │
                          └──────┬───────┘
                                 │
                    HA entity state updates
```

## Supported Devices

Any Bluetti device that appears in the Bluetti mobile app should work, including:
- AC300, AC200, AC200MAX, AC200P, AC200L
- AC500, AC180, AC60
- EB3A, EB55, EB70
- EP500, EP500Pro, EP600
- And others

## Installation

### HACS (Recommended)

1. Make sure [HACS](https://hacs.xyz/) is installed in your Home Assistant instance

2. Click the button below to add this repository to HACS:

   [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=thierrycoopman&repository=battery-ha&category=integration)

   Or manually: open HACS → click the three dots menu → **Custom repositories** → paste `https://github.com/thierrycoopman/battery-ha` → select **Integration**

3. Search for **Bluetti Cloud** in HACS and click **Download**

4. Restart Home Assistant

### Manual Installation

1. Download the `custom_components/bluetti_cloud` folder from this repository
2. Copy it to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

After installation, click the button below to start setup:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=bluetti_cloud)

Or manually:

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Bluetti Cloud**
3. Enter your Bluetti account email and password (same credentials as the Bluetti mobile app)
4. Select which devices to monitor
5. Done! Entities will appear automatically

## Entities

For each selected device, the following entities are created:

### Sensors
| Entity | Description | Unit | Source |
|--------|-------------|------|--------|
| Battery | Battery state of charge | % | MQTT / REST |
| Pack Voltage | Battery pack voltage | V | MQTT |
| Pack Current | Battery pack current (negative = discharging) | A | MQTT |
| Charging Status | Current charging state (charging/discharging/standby) | — | MQTT |
| Charge Time Remaining | Estimated time to full charge | min | MQTT |
| Discharge Time Remaining | Estimated time to empty | min | MQTT |
| Solar Power | PV input power | W | REST |
| Grid Input Power | Grid/AC charging power | W | REST |
| AC Output Power | AC output power | W | REST |
| DC Output Power | DC output power | W | REST |
| Grid Feed-in Power | Power fed back to grid | W | REST |
| Energy Today | Energy generated today | kWh | REST |
| Energy This Month | Energy generated this month | kWh | REST |
| Energy This Year | Energy generated this year | kWh | REST |
| Lifetime Energy | Total lifetime energy | kWh | REST |

### Binary Sensors
| Entity | Description |
|--------|-------------|
| Online | Device cloud connectivity status |

### Switches
| Entity | Description |
|--------|-------------|
| AC Output | Toggle AC output on/off (via MQTT) |
| DC Output | Toggle DC output on/off (via MQTT) |

## How It Works

The integration uses a **hybrid MQTT + REST** architecture:

1. **MQTT (primary)** — Connects to `iot.bluettipower.com:18760` using mTLS client certificates and TOTP authentication. Receives real-time Modbus RTU telemetry frames with battery, pack, and switch state data. Also sends switch commands.

2. **REST API (complementary)** — Polls the Bluetti mobile app API every 60 seconds for power readings, energy totals, and online status. These fields are not available via MQTT on older devices (protocolVer < 2001).

3. **Data merge** — MQTT data takes precedence for fields it provides (more current). REST fills in fields MQTT cannot provide.

4. **Fallback** — If MQTT cannot connect (e.g., certificate issues), the integration automatically falls back to REST-only mode with 30-second polling.

## Troubleshooting

### "Invalid email or password"
Ensure you're using the same credentials as the Bluetti mobile app. The password is case-sensitive.

### "Cannot connect to Bluetti Cloud"
Check your internet connection. The Bluetti cloud servers may occasionally be unreachable.

### MQTT sensors show "unavailable"
MQTT telemetry sensors (Pack Voltage, Pack Current, Charging Status, etc.) require an active MQTT connection. Check your HA logs for MQTT connection errors. The integration will fall back to REST polling for non-MQTT sensors.

### Switches not responding
Switch control requires MQTT connectivity. If MQTT cannot connect, switches will not work. Check the HA log for `"MQTT telemetry unavailable"` messages. Common causes:
- `pycryptodome` not installed (required for mTLS certificate exchange)
- Network firewall blocking port 18760 to `iot.bluettipower.com`
- Bluetti token expired (restart the integration)

### Device shows as offline
If the device shows as offline in this integration but online in the mobile app, this is expected for some device models. The `iotSession` field may report "Offline" even when the device is controllable. MQTT control and telemetry can still work in this state.

## Development

```bash
# Clone the repo
git clone https://github.com/thierrycoopman/battery-ha.git
cd battery-ha

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install pytest pytest-asyncio aiohttp pycryptodome paho-mqtt homeassistant voluptuous
```

## License

MIT — see [LICENSE](LICENSE)
