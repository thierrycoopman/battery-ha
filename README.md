# Bluetti Cloud — Home Assistant Integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/thierrycoopman/battery-ha)](https://github.com/thierrycoopman/battery-ha/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Vibe Coded](https://img.shields.io/badge/Vibe%20Coded-with%20Claude%20Code-cc785c?logo=claude&logoColor=cc785c)](https://claude.ai/code)

> **Personal Project Disclaimer**
>
> This integration exists because I needed it. My AC300 + 2x B300 battery packs showed as "offline" in every existing Home Assistant integration, even though they worked perfectly fine in the Bluetti mobile app. No existing solution supported my hardware, so I built my own — and later extended it to my APEX 300.
>
> **This is a personal project scratching a personal itch.** It works on my setup (an AC300 with battery packs, and an APEX 300 with a D1 hub and a B300), but there is absolutely no guarantee it will work on yours. There is no support, no roadmap, and no commitment to maintain this beyond my own needs. If you choose to use it, **you do so entirely at your own risk and responsibility.**
>
> I'm sharing it in case someone else has the same problem, but I cannot help you debug your specific device, fix issues with models I don't own, or provide any form of support.

---

## Why This Integration?

The official Bluetti HA integration uses OAuth2 and the `/ha/v1/` API namespace, which only supports newer device models. Older devices like the AC300 show as "offline" even when they're fully operational in the Bluetti mobile app.

This integration talks to the same private cloud API and MQTT broker as the Bluetti mobile app, so devices the official integration reports as unsupported can still be monitored — and, on supported models, controlled.

## Supported Devices

| Device | Protocol | MQTT Telemetry | AC/DC Control | Battery Detail | Tested |
|--------|:--------:|:--------------:|:-------------:|:--------------:|:------:|
| **AC300 + B300** | V1 | Yes (FC=16 push) | **Yes** | Per-pack (up to 4) | **Tested** |
| **APEX 300 (AP300)** | V2 (2nd-gen IoT) | Yes (poll)¹ | **No**¹ | Per-battery² | **Tested** (telemetry) |
| AC200 / AC200P / AC200L / AC200MAX | V1 or V2³ | Likely | Likely on V1 | Likely | Untested |
| AC500 | V1 or V2³ | Likely | Likely on V1 | Likely | Untested |
| AC180, AC60 | V1 or V2³ | Likely | Likely on V1 | Unknown | Untested |
| EP500, EP500Pro, EP600 | V1 or V2³ | Likely | Likely on V1 | Likely | Untested |
| EB3A, EB55, EB70 | V1 or V2³ | Likely | Likely on V1 | N/A (internal battery) | Untested |

> ¹ The APEX 300 (cloud model code `AP300`, protocol version 2015) uses the
> 2nd-generation IoT protocol (`iotPayloadVer` 1.2 — a `01 F8 0F …` envelope,
> Modbus slave 0). As of v0.7.0 it has **real-time MQTT telemetry** (SOC,
> battery voltage, charging status, output states; ~10s refresh) layered on REST
> for power/energy. **Output control is not yet implemented** — AC/DC/PV/grid
> outputs appear as **read-only binary sensors** (state only). Control (V2
> switch registers) is a planned follow-up.
>
> ² Sub-devices are enumerated from the device's `NODE_INFO` registry: each
> battery and addition (D1 hub / A1 hub / SolarX) becomes a connectivity sensor,
> and batteries are identified by their specific model (**B300 / B300K / B500K**,
> etc.) with their own state-of-charge sensor. Per-battery voltage/current/SOH
> are only reported by the hardware under load, so they are omitted while idle
> rather than shown as 0.
>
> ³ Which protocol a device speaks is determined by its `protocolVer`: **< 2000
> = V1** (unprompted FC=16 pushes, legacy payload framing, control implemented),
> **≥ 2000 = V2** (actively polled, `01 F8 0F …` payload envelope, Modbus slave 0,
> control not yet implemented). A model without an explicit profile falls back by
> generation — a V2 device gets V2 framing and telemetry — so an unlisted device
> has a fair chance of working for monitoring. Control is only enabled on models
> where it has been verified.

**Any Bluetti device that appears in the Bluetti mobile app should work in principle.** The integration uses the same cloud API and MQTT protocol as the app. However, different models use different protocol versions, register layouts, and payload framing. The configurations actually tested are an **AC300 with B300 packs** (full telemetry + control) and an **APEX 300 with a D1 hub and a B300** (telemetry only).

> If you try this on a different device and it works (or doesn't), feel free to open an issue to let me know — I'll update this table.

## Features

- **Real-time MQTT telemetry** — Battery SOC, voltage, current, charging status, and output states, updated live over MQTT
- **Two device protocols** — V1 devices (AC300) push data unprompted (FC=16); V2 / 2nd-gen IoT devices (APEX 300, `protocolVer` ≥ 2000) are actively polled using a different payload envelope
- **Sub-device discovery** — On V2 devices, batteries and additions (D1 hub, A1 hub, SolarX) are enumerated and tracked individually, with batteries identified by model (B300 / B300K / B500K, …)
- **Per-battery sensors** — Individual state of charge per battery
- **AC/DC control** — Switch entities on devices that support control (AC300); devices without control expose read-only output-state sensors instead
- **Power monitoring** — PV input, grid input, AC output, DC output, grid feed-in (W)
- **Energy tracking** — Daily, monthly, yearly, and lifetime totals (kWh) for the HA Energy Dashboard
- **Automatic MQTT reconnection** — Exponential backoff (30s → 60s → 120s → 5min) with fresh credentials each attempt
- **Graceful degradation** — If MQTT is unavailable, falls back to REST-only polling and keeps retrying in the background
- **Reconfigure support** — Add or remove devices on an existing entry without losing history

### Architecture

```
 MQTT (real-time)                                    REST API (30–60s)
                        ┌────────────────────┐
 V1: FC=16 pushes  ───> │                    │ <───  homeDevices + lastAlive
 V2: FC=03 polling ───> │    Coordinator     │ <───  energyDetail
 node/sub-devices  ───> │                    │ <───  online status
 switch echoes     ───> └─────────┬──────────┘
                                  │
 SUB/{model}/{subSn} ──>          │   device profile decides the data path,
 PUB/{model}/{subSn} <──          │   registers, and payload framing per model
                                  │
                        HA entity state updates
```

MQTT data takes precedence where it is available (it is more current). REST supplies power readings, energy totals, and online status that MQTT does not provide on some models. A per-model **device profile** (`api/profiles.py`) selects the data path (`mqtt+rest` vs `rest_only`), Modbus slave address, payload version, register blocks, and whether the device is controllable — so adding a model is a profile entry rather than new branching logic.

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

### Per-Battery Sensors (dynamic)

Created automatically as batteries are discovered. How they appear depends on the device protocol:

| Device type | Entities |
|---|---|
| **V1 (AC300)** — packs are cycled through by the device | `Pack N Voltage` (V), `Pack N SOC` (%), `Pack N Charging Status` |
| **V2 (APEX 300)** — batteries are discovered as sub-devices | `<model> (node N) Battery` (%) — e.g. **`B300 (node 51) Battery`** |

> On V2 devices, per-battery **voltage / current / SOH** are only populated by
> the hardware under load. They are omitted while a pack is idle rather than
> reported as a misleading `0`.

### Binary Sensors
| Entity | Description |
|--------|-------------|
| Cloud Connected | Device cloud connectivity status |
| IoT Session | Device IoT session status |

**Sub-devices (V2 devices)** — one connectivity sensor per discovered node, created dynamically:

| Entity | Description |
|--------|-------------|
| `<model> (node N)` | Online state of a battery or addition — e.g. `B300 (node 51)`, `D1 Hub (HD1) (node 11)` |

Each carries attributes: model name and code, slave address, whether it is a battery, warning/error flags, serial, and (for batteries) pack model, SOC and cell count.

**Devices without output control** additionally expose their outputs as read-only binary sensors instead of switches:

| Entity | Description |
|--------|-------------|
| AC Output | AC output on/off state (read-only) |
| DC Output | DC output on/off state (read-only) |
| Solar Input | PV input on/off state (read-only) |
| Grid Input | Grid input on/off state (read-only) |

### Switches

Created only for devices the integration can control (currently V1 devices such as the AC300 — **not** the APEX 300):

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

### Adding a device later

If you bind a new device to your Bluetti account after setup, you don't need to
remove the integration: go to **Settings → Devices & Services → Bluetti Cloud →
⋮ → Reconfigure** and tick the new device. Existing entities and history are
preserved.

## Troubleshooting

### MQTT sensors show "Unknown"
MQTT sensors require an active MQTT connection. Check your HA logs — you should see `"MQTT telemetry active"` shortly after startup. If MQTT fails, the integration will retry automatically with exponential backoff (check for `"MQTT reconnect scheduled"` messages). Common blockers:
- Network firewall blocking port 18760 to `iot.bluettipower.com`
- `pycryptodome` not installed (required for mTLS certificate exchange)

### Per-battery or sub-device sensors not appearing
These are created dynamically as the integration discovers them.
- **AC300 (V1):** within 1–2 FC=16 push cycles (~30s after MQTT connects). Look for `"discovered battery pack"` in the logs.
- **APEX 300 (V2):** on the first poll cycle after MQTT connects, via the device's sub-device registry. Look for `"MQTT node info"` in debug logs.

### No switches for my APEX 300
Expected. Output **control** is not implemented for the APEX 300 yet — its AC/DC/PV/grid outputs appear as **read-only binary sensors** showing state only. Telemetry (SOC, voltage, charging status) works normally.

### Switches not responding
Switch control requires MQTT. If MQTT is disconnected, switches won't work. The integration keeps retrying in the background — they start working again once MQTT reconnects.

### A device I just added to my Bluetti account isn't there
The device list is stored in the config entry, so a restart alone won't pick it up. Use **⋮ → Reconfigure** (see [Adding a device later](#adding-a-device-later)).

### Device shows as offline
If a device shows offline here but online in the mobile app, this is expected for some models — the `iotSession` field can report offline while MQTT telemetry and control still work.

### "Invalid email or password"
Ensure you're using the same credentials as the Bluetti mobile app. The password is case-sensitive.

## How This Was Built

This entire integration was **vibe coded with [Claude Code](https://claude.ai/code)** — Anthropic's agentic coding tool. Every line of code, every test, every reverse-engineering session was done in conversation with Claude.

The Bluetti ecosystem has no public API documentation. Getting from "my device shows offline in HA" to full real-time telemetry required reverse engineering the Bluetti Android APK to extract the mobile app's private API endpoints, the MQTT authentication chain (mTLS + server-time TOTP), and the Modbus register maps.

The APEX 300 needed a second round: it ignores the protocol the AC300 uses. It turned out to speak Bluetti's **2nd-generation IoT protocol** — a different payload envelope (`01 F8 0F …` instead of a single `0x01` byte), Modbus slave `0` instead of `1`, and a set of shared encoding conventions (ASCII fields byte-swapped within each register, serial numbers with reversed register order, word-swapped 32-bit values). Every protocol finding in this integration was verified against real captured payloads from live hardware.

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
pip install pytest pytest-asyncio aiohttp pycryptodome paho-mqtt homeassistant voluptuous ruff

# Run tests (152 tests) and lint
python -m pytest tests/ -v
ruff check custom_components/ tests/
```

### Layout

| Path | Purpose |
|---|---|
| `custom_components/bluetti_cloud/api/` | Cloud REST client, MQTT client, crypto/TOTP, Modbus framing + parsers, device profiles |
| `custom_components/bluetti_cloud/coordinator.py` | REST polling and orchestration |
| `custom_components/bluetti_cloud/mqtt_manager.py` | MQTT lifecycle, reconnection, polling, telemetry parsing |
| `custom_components/bluetti_cloud/{sensor,binary_sensor,switch}.py` | Entity platforms |
| `scripts/discovery/` | Read-only probe scripts used to investigate a device against a live account (see its README) |
| `tests/fixtures/` | Real captured device payloads used as test fixtures |

## License

MIT — see [LICENSE](LICENSE)
