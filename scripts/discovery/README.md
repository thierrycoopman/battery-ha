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
| `06_e2e_both.py` | Drive the real coordinator REST path for all devices | No (read-only) |

`02` and `03` need `DEVICE_SN` and `MODEL` filled in from `01`'s output.

Findings for the AP300 investigation are recorded locally in
`docs/apex300-findings.md` (the `docs/` directory is gitignored) and summarised
in the PR description; raw payloads are saved under `tests/fixtures/apex300/`
for fixture-based tests.

> The AP300 (APEX 300) turned out to be REST-only for this integration — it does
> not respond to the MQTT control protocol — so no control-test script was
> needed. If you add a device that *is* MQTT-controllable, write a control
> script that prompts before each toggle and restores the original state, and
> make sure nothing critical is connected before running it.
