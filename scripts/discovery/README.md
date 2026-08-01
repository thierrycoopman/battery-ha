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

## Scripts (run order)

| Script | What it does | Writes to device? |
|--------|--------------|-------------------|
| `01_rest_recon.py` | Login, list devices, dump model/protocolVer/telemetry/energy | No (read-only) |
| `02_mqtt_observe.py` | Connect MQTT, subscribe, log unprompted pushes for 90s | No (read-only) |
| `03_register_dump.py` | FC=03 reads of known register blocks, parse best-effort | No (read-only) |
| `04_control_test.py` | Toggle AC/DC outputs with confirmation, then restore | **Yes — flips outputs** |

`02`–`04` need `DEVICE_SN` and `MODEL` filled in from `01`'s output.

Findings are recorded in `docs/apex300-findings.md`; raw payloads are saved
under `tests/fixtures/apex300/` for later fixture-based tests.

## Safety

`04_control_test.py` physically switches AC then DC outputs on the device.
Make sure nothing critical is connected before running it. It prompts before
each toggle and restores the original state afterward.
