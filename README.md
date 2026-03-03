# Bluetti Cloud — Home Assistant Integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/thierrycoopman/battery-ha)](https://github.com/thierrycoopman/battery-ha/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A custom Home Assistant integration that connects to Bluetti power stations via the Bluetti Cloud mobile app API. This integration supports devices that are **not covered** by the official Bluetti HA integration (e.g., AC300, AC200, and other older models).

## Why This Integration?

The official Bluetti HA integration uses OAuth2 and the `/ha/v1/` API namespace, which only supports newer device models. Older devices like the AC300 show as "offline" even when they're fully operational in the Bluetti mobile app.

This integration uses the same API as the Bluetti mobile app, providing full access to device telemetry and control for all cloud-connected Bluetti devices.

## Features

- **Battery monitoring** — State of Charge (SoC), total battery percentage
- **Power monitoring** — PV input, grid input, AC output, DC output (in Watts)
- **Online status** — Binary sensor showing device connectivity
- **AC/DC control** — Switch entities to toggle AC and DC outputs on/off
- **30-second polling** — Automatic data refresh every 30 seconds
- **Multi-device support** — Monitor and control multiple Bluetti devices

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
| Entity | Description | Unit |
|--------|-------------|------|
| Battery | Battery state of charge | % |
| Total Battery | Total battery percentage | % |
| PV Input | Solar panel input power | W |
| Grid Input | Grid/AC charging power | W |
| AC Output | AC output power | W |
| DC Output | DC output power | W |

### Binary Sensors
| Entity | Description |
|--------|-------------|
| Online | Device cloud connectivity status |

### Switches
| Entity | Description |
|--------|-------------|
| AC Output | Toggle AC output on/off |
| DC Output | Toggle DC output on/off |

## Troubleshooting

### "Invalid email or password"
Ensure you're using the same credentials as the Bluetti mobile app. The password is case-sensitive.

### "Cannot connect to Bluetti Cloud"
Check your internet connection. The Bluetti cloud servers may occasionally be unreachable.

### Switches not working
The AC/DC switch control uses the HA fulfillment API endpoint. If your device model doesn't support this endpoint, the switches will appear as unavailable.

### Device shows as offline
If the device shows as offline in this integration but online in the mobile app, please open an issue with your device model.

## Development

```bash
# Clone the repo
git clone https://github.com/thierrycoopman/battery-ha.git
cd bluetti-ha

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install pytest pytest-asyncio aiohttp pycryptodome homeassistant voluptuous

# Run tests
python -m pytest tests/ -v
```

## License

MIT — see [LICENSE](LICENSE)
