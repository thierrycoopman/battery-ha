# Bluetti discovery scripts

Live-account probe scripts used to reverse-engineer and verify a Bluetti
device's protocol before adding it to the integration. They reuse the real
`custom_components/bluetti_cloud/api/` modules (login, crypto, TOTP, MQTT,
Modbus) so what they exercise matches what the integration ships.

## Requirements

- The dev venv with Home Assistant installed (the `bluetti_cloud` package
  `__init__` imports HA). Run scripts with `./venv/bin/python`.
- A `.env` file at the repo root (gitignored) — copy `.env.example`:

  ```
  BLUETTI_EMAIL=you@example.com
  BLUETTI_PASSWORD=your-password
  ```

## Scripts

| Script | What it does | Writes to device? |
|--------|--------------|-------------------|
| `01_rest_recon.py` | Login, list devices, dump model / `protocolVer` / telemetry / energy | No |
| `02_mqtt_observe.py` | Connect MQTT, subscribe, log unprompted pushes for 90s | No |
| `03_register_dump.py` | FC=03 reads of known register blocks, parsed best-effort | No |
| `06_e2e_both.py` | Drive the real coordinator REST path for all devices | No |
| `07_ap300_mqtt_v2.py` | V2 (2nd-gen IoT) telemetry via the shipped MQTT path | No |
| `08_ap300_nodes.py` | Enumerate sub-devices (batteries, hubs) via `NODE_INFO` | Query-write¹ |

Scripts other than `01` have `DEVICE_SN` / `MODEL` constants near the top —
fill them in from `01`'s output.

¹ `08` writes a *selector* to the `NODE_INFO` register to ask the device to
report its node list. It changes no output or setting.

## Protocol cheat-sheet

Determined from the app and verified against live hardware:

| | V1 (`protocolVer` < 2000) | V2 / 2nd-gen IoT (≥ 2000) |
|---|---|---|
| Payload framing | `0x01` + Modbus RTU | `01 F8 0F <reg:2> 00×5` + Modbus RTU |
| Modbus slave | `1` | `0` |
| Telemetry | device pushes FC=16 unprompted | must be polled (FC=03) |
| Topics | `SUB/{model}/{subSn}` → `PUB/{model}/{subSn}` | same |

**Encoding conventions** (V2 parsers): ASCII fields are byte-swapped within
each 16-bit register (raw `3B00` = `B300`); serial numbers concatenate
registers in reverse order and render as decimal; 32-bit values are
word-swapped (low register first); per-pack voltage is `/100` while aggregate
voltage and currents are `/10`; temperatures are `raw − 40`.

## Safety

These scripts talk to real hardware. Reads are harmless; writes are not.

- Only `08` writes, and only an informational selector.
- **If you add a control script**, prompt before each toggle, restore the
  original state, and make sure nothing critical is connected.
- **Mind adjacent registers.** On V2 devices `2011` = AC switch and `2012` =
  DC switch, but **`2013` = system power off** — an off-by-one on the address
  shuts the unit down. `2206` is a factory reset and `2233` a battery-aging
  routine. Double-check any register you write.

## Findings

Per-device findings are recorded locally in `docs/` (gitignored) and summarised
in the relevant pull requests. Raw captured payloads live under
`tests/fixtures/` and are used as test fixtures, so parser changes are verified
against real device data rather than synthetic bytes.
