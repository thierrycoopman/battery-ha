# Bluetti Cloud — Home Assistant Integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/thierrycoopman/battery-ha)](https://github.com/thierrycoopman/battery-ha/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Vibe Coded](https://img.shields.io/badge/Vibe%20Coded-with%20Claude%20Code-cc785c?logo=claude&logoColor=cc785c)](https://claude.ai/code)

> **Personal Project Disclaimer**
>
> This integration exists because I needed it. My AC300 + 2x B300 battery packs showed as "offline" in every existing Home Assistant integration, even though they worked perfectly fine in the Bluetti mobile app. No existing solution supported my hardware, so I built my own.
>
> **This is a personal project scratching a personal itch.** It works on my setup (AC300 with 2 battery packs), but there is absolutely no guarantee it will work on yours. There is no support, no roadmap, and no commitment to maintain this beyond my own needs. If you choose to use it, **you do so entirely at your own risk and responsibility.**
>
> I'm sharing it in case someone else has the same problem, but I cannot help you debug your specific device, fix issues with models I don't own, or provide any form of support.

---

## Why This Integration?

The official Bluetti HA integration uses OAuth2 and the `/ha/v1/` API namespace, which only supports newer device models. Older devices like the AC300 show as "offline" even when they're fully operational in the Bluetti mobile app.

This integration uses the same API as the Bluetti mobile app, providing full access to device telemetry and control for all cloud-connected Bluetti devices.

## Supported Devices

| Device | MQTT Telemetry | AC/DC Control | Per-Pack Sensors | Tested |
|--------|:--------------:|:-------------:|:----------------:|:------:|
| **AC300 + B300** | Yes (FC=16 push) | Yes | Yes (up to 4 packs) | **Tested** |
| AC200, AC200P, AC200L, AC200MAX | Likely (V2 polling) | Likely | Likely | Untested |
| AC500 | Likely | Likely | Likely | Untested |
| AC180, AC60 | Likely | Likely | Unknown | Untested |
| EP500, EP500Pro, EP600 | Likely | Likely | Likely | Untested |
| EB3A, EB55, EB70 | Likely | Likely | N/A (internal battery) | Untested |

**Any Bluetti device that appears in the Bluetti mobile app should work in principle.** The integration uses the same cloud API and MQTT protocol as the app. However, different models may use different protocol versions, register layouts, or Modbus function codes. The only configuration tested and confirmed working is the **AC300 with 2x B300 battery packs**.

> If you try this on a different device and it works (or doesn't), feel free to open an issue to let me know — I'll update this table.

## Features

- **Real-time MQTT telemetry** — Battery SOC, voltage, current, charging status, and switch states updated in real-time via MQTT
- **Per-battery pack sensors** — Individual voltage, SOC, and charging status for each connected battery pack (AC300 cycles through packs automatically)
- **AC/DC control** — Switch entities to toggle AC and DC outputs via MQTT with optimistic state updates
- **Power monitoring** — PV input, grid input, AC output, DC output, grid feed-in (in Watts)
- **Energy tracking** — Daily, monthly, yearly, and lifetime energy totals (kWh) for the HA Energy Dashboard
- **Automatic MQTT reconnection** — Exponential backoff retry (30s → 60s → 120s → 5min) with fresh credentials on each attempt
- **Graceful degradation** — If MQTT is unavailable, falls back to REST-only polling (30s) and keeps retrying MQTT in the background

### Architecture

```
                                  ┌──────────────────┐
  MQTT (real-time, ~1s)           │                  │    REST API (every 60s)
  ┌─ FC=16 data pushes (AC300)   │                  │
  ├─ Battery SOC, voltage, amps  │   Coordinator    │ <── homeDevices + lastAlive
  ├─ Per-pack cycling (reg 3006) │   (data merge)   │     + energyDetail
  └─ Switch state echoes         │                  │
       │                         └────────┬─────────┘
       │    SUB/{model}/{subSn} ──>       │
       └──  PUB/{model}/{subSn} <──       │
            Modbus RTU frames    HA entity state updates
```

MQTT data takes precedence for fields it provides (more current). REST fills in power readings, energy totals, and online status that MQTT doesn't provide on older devices.

## Entities

### Sensors
| Entity | Description | Unit | Source |
|--------|-------------|------|--------|
| Battery | Battery state of charge | % | MQTT / REST |
| Charging Status | Current charging state (charging/discharging/standby) | — | MQTT |
| Battery Total Voltage | Aggregate battery voltage | V | MQTT |
| Battery Total Current | Aggregate battery current (negative = discharging) | A | MQTT |
| Solar Power | PV input power | W | REST |
| Grid Input Power | Grid/AC charging power | W | REST |
| AC Output Power | AC output power | W | REST |
| DC Output Power | DC output power | W | REST |
| Grid Feed-in Power | Power fed back to grid | W | REST |
| Energy Today | Energy generated today | kWh | REST |
| Energy This Month | Energy generated this month | kWh | REST |
| Energy This Year | Energy generated this year | kWh | REST |
| Lifetime Energy | Total lifetime energy | kWh | REST |

### Per-Battery Pack Sensors (dynamic)

Created automatically when battery packs are discovered (e.g., 2 packs = 6 sensors):

| Entity | Description | Unit |
|--------|-------------|------|
| Pack N Voltage | Individual pack voltage | V |
| Pack N SOC | Individual pack state of charge | % |
| Pack N Charging Status | Individual pack charging state | — |

### Binary Sensors
| Entity | Description |
|--------|-------------|
| Cloud Connected | Device cloud connectivity status |
| IoT Session | MQTT IoT session status |

### Switches
| Entity | Description |
|--------|-------------|
| AC Output | Toggle AC output on/off (via MQTT) |
| DC Output | Toggle DC output on/off (via MQTT) |

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

## Troubleshooting

### MQTT sensors show "Unknown"
MQTT sensors require an active MQTT connection. Check your HA logs — you should see `"MQTT telemetry active"` shortly after startup. If MQTT fails, the integration will retry automatically with exponential backoff (check for `"MQTT reconnect scheduled"` messages). Common blockers:
- Network firewall blocking port 18760 to `iot.bluettipower.com`
- `pycryptodome` not installed (required for mTLS certificate exchange)

### Per-pack sensors not appearing
Per-battery pack sensors are created dynamically when the integration discovers connected packs. For AC300, this happens within 1-2 FC=16 push cycles (~30s after MQTT connects). Check logs for `"discovered battery pack"` messages.

### Switches not responding
Switch control requires MQTT. If MQTT is disconnected, switches won't work. The integration will keep retrying MQTT in the background — switches will start working once MQTT reconnects.

### Device shows as offline
If the device shows as offline in this integration but online in the mobile app, this is expected for some models. The `iotSession` field may report "Offline" even when the device is controllable via MQTT. MQTT control and telemetry can still work in this state.

### "Invalid email or password"
Ensure you're using the same credentials as the Bluetti mobile app. The password is case-sensitive.

## How This Was Built

This entire integration was **vibe coded with [Claude Code](https://claude.ai/code)** — Anthropic's agentic coding tool. Every line of code, every test, every reverse-engineering session was done in conversation with Claude.

The Bluetti ecosystem has no public API documentation. Getting from "my device shows offline in HA" to "full real-time telemetry with per-battery pack sensors" required reverse engineering the Bluetti Android APK (v3.0.6) to extract the mobile app's private API endpoints, MQTT authentication chain (mTLS + TOTP), and Modbus register maps.

No code was written by hand. This README was also written by Claude.

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

# Run tests (114 tests)
python -m pytest tests/ -v
```

## License

MIT — see [LICENSE](LICENSE)
