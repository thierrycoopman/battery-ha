# Bluetti Cloud — Home Assistant Integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/thierrycoopman/battery-ha)](https://github.com/thierrycoopman/battery-ha/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Vibe Coded](https://img.shields.io/badge/Vibe%20Coded-with%20Claude%20Code-cc785c?logo=claude&logoColor=cc785c)](https://claude.ai/code)

> **Personal Project Disclaimer**
>
> This integration exists because I needed it. My AC300 + 2x B300 battery packs showed as "offline" in every existing Home Assistant integration, even though they worked perfectly fine in the Bluetti mobile app. No existing solution supported my hardware, so I built my own.
>
> **This is a personal project scratching a personal itch.** It works on my setup (AC300 with 2 battery packs), but there is absolutely no guarantee it will work on yours. There is no support, no roadmap, and no commitment to maintain this beyond my own needs. If you choose to use it, **you do so entirely at your own risk and responsibility.**
>
> I'm sharing it in case someone else has the same problem, but I cannot help you debug your specific device, fix issues with models I don't own, or provide any form of support.

---

## How This Was Built

This entire integration was **vibe coded with [Claude Code](https://claude.ai/code)** — Anthropic's agentic coding tool. Every line of code, every test, every reverse-engineering session was done in conversation with Claude.

### The journey

The Bluetti ecosystem has no public API documentation. Getting from "my device shows offline in HA" to "full real-time telemetry with per-battery pack sensors" required weeks of reverse engineering:

1. **Started with the official HA API** (`/ha/v1/` namespace) — discovered it only supports newer devices. My AC300 was invisible.

2. **Decompiled the Bluetti Android APK** (v3.0.6) — extracted the mobile app's private API endpoints, authentication flow, and encryption schemes. Discovered the app uses a completely different API (`/api/blusmartprod/`, `/api/bluiotdata/`) with its own `APP_ID`, SHA-256 password hashing, and AES-encrypted password fields.

3. **Cracked the MQTT authentication** — the app connects to an MQTT broker (`iot.bluettipower.com:18760`) using mTLS with P12 client certificates. Getting a valid certificate requires a chain of: server-time fetch → AES signature decryption → TOTP generation → AES cert password encryption → P12 download → PEM extraction. Every step was reverse-engineered from the APK's Java bytecode.

4. **Decoded the Modbus protocol** — the MQTT messages are Modbus RTU frames (function codes 0x03 and 0x06) with a protocol prefix byte. Register maps were extracted from `ProtocolParserV2.java` and `ProtocolAddrV2.java` in the decompiled APK.

5. **Discovered active polling** (v0.5.0) — the device doesn't push telemetry voluntarily. The mobile app sends FC=03 read requests for specific register addresses (100 for homeData, 6000 for PackMainInfo, 6100 for per-battery PackItemInfo), and the device responds. Without these requests, many sensors stayed "Unknown".

### Build process

Claude Code handled the full development cycle:
- **Architecture design** — hybrid MQTT+REST coordinator pattern, two-phase MQTT connect (async HTTP + blocking paho), thread-safe telemetry dispatch
- **Implementation** — all Python code, Home Assistant platform integrations (sensors, switches, binary sensors, config flow), Modbus frame builders/parsers
- **Testing** — 101 unit tests covering CRC calculations, frame building/parsing, register maps, sensor descriptions, switch commands, coordinator data flow
- **Reverse engineering** — APK decompilation analysis, protocol documentation, iterative testing against real hardware
- **Debugging** — traced issues like the server-time TOTP requirement (local time doesn't work), the empty `token_type` field in OAuth responses, the `iotSession` always showing "Offline" even when devices are controllable

No code was written by hand. This README was also written by Claude.

---

## Why This Integration?

The official Bluetti HA integration uses OAuth2 and the `/ha/v1/` API namespace, which only supports newer device models. Older devices like the AC300 show as "offline" even when they're fully operational in the Bluetti mobile app.

This integration uses the same API as the Bluetti mobile app, providing full access to device telemetry and control for all cloud-connected Bluetti devices.

## Features

- **Active MQTT polling** — Sends Modbus FC=03 read requests every 10s for real-time battery data, matching the mobile app's behavior
- **Per-battery pack sensors** — Individual voltage, current, SOC, SOH, temperature, and charging status for each connected battery pack
- **Real-time MQTT telemetry** — Battery SOC, pack voltage/current, charging status updated via MQTT push
- **REST API fallback** — Power readings, energy totals, and online status polled every 60s (30s if MQTT unavailable)
- **AC/DC control** — Switch entities to toggle AC and DC outputs via MQTT with optimistic state updates
- **Power monitoring** — PV input, grid input, AC output, DC output, grid feed-in (in Watts)
- **Energy tracking** — Daily, monthly, yearly, and lifetime energy totals (kWh) for the HA Energy Dashboard
- **Online status** — Binary sensor showing device connectivity
- **Multi-device support** — Monitor and control multiple Bluetti devices
- **Graceful degradation** — If MQTT is unavailable, the integration falls back to REST-only polling

### Architecture

```
                                  ┌──────────────────┐
  MQTT Polling (every 10s)        │                  │    REST API (every 60s)
  ┌─ FC=03 reg 100 (homeData)     │                  │
  ├─ FC=03 reg 6000 (PackMain)    │   Coordinator    │ <── homeDevices + lastAlive
  ├─ FC=03 reg 6100 slave=1       │                  │     + energyDetail
  └─ FC=03 reg 6100 slave=2       │                  │
       │                          └────────┬─────────┘
       │    SUB/{model}/{subSn} ──>        │
       └──  PUB/{model}/{subSn} <──        │
            Modbus RTU frames     HA entity state updates
```

## Supported Devices

Any Bluetti device that appears in the Bluetti mobile app should work, including:
- AC300, AC200, AC200MAX, AC200P, AC200L
- AC500, AC180, AC60
- EB3A, EB55, EB70
- EP500, EP500Pro, EP600
- And others

**Tested on:** AC300 + 2x B300 battery packs. Other models may or may not work — see disclaimer above.

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
| Battery Total Voltage | Aggregate battery voltage from PackMainInfo | V | MQTT |
| Battery Total Current | Aggregate battery current from PackMainInfo | A | MQTT |
| Battery Total SOC | Aggregate state of charge from PackMainInfo | % | MQTT |
| Battery Health | Battery state of health (SOH) | % | MQTT |
| Battery Temperature | Average battery temperature | °C | MQTT |
| Time to Full Charge | Time until batteries are fully charged | min | MQTT |
| Time to Empty | Time until batteries are empty | min | MQTT |
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

Created automatically for each discovered battery pack (e.g., 2 packs = 12 sensors):

| Entity | Description | Unit |
|--------|-------------|------|
| Pack N Voltage | Individual pack voltage | V |
| Pack N Current | Individual pack current | A |
| Pack N SOC | Individual pack state of charge | % |
| Pack N Health | Individual pack state of health | % |
| Pack N Temperature | Individual pack temperature | °C |
| Pack N Charging Status | Individual pack charging state | — |

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

The integration uses a **hybrid MQTT + REST** architecture with **active polling**:

1. **MQTT Active Polling (primary)** — Connects to `iot.bluettipower.com:18760` using mTLS client certificates and TOTP authentication. Every 10 seconds, sends Modbus FC=03 read requests for homeData (register 100), PackMainInfo (register 6000), and PackItemInfo (register 6100, one per battery pack). The device responds with the requested data on the PUB topic. Responses are routed to the correct parser based on request tracking (FC=03 responses don't include the register address).

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

### Per-pack sensors not appearing
Per-battery pack sensors are created dynamically when the integration discovers how many packs are connected. This happens after the first successful PackMainInfo read (within 10-20 seconds of MQTT connecting). If they don't appear, check logs for MQTT polling errors.

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

# Run tests
python -m pytest tests/ -v
```

## License

MIT — see [LICENSE](LICENSE)
