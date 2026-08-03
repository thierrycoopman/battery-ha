# Prompt: build a Bluetti APEX 300 dashboard

Copy everything below the line into Claude Code running inside Home Assistant.

---

Build me a Home Assistant dashboard for my Bluetti APEX 300 home battery system.

## Before you design anything

Discover the real entities first — do not assume the IDs below, they depend on
how I named my devices. The integration domain is `bluetti_cloud`.

1. List every entity belonging to it and note its device, unit and device_class.
2. Check which are currently *unavailable* — several are unavailable **by
   design** (see "Expected gaps"), so don't treat them as broken or drop them.
3. Tell me what you found before building, and flag anything that contradicts
   the structure described here.

## My system

One main unit with expansions attached. Each appears as a **separate device**,
linked to the main unit:

```
AP300 (APEX 300)      the inverter/main unit
├── Internal Battery  the main unit's own pack
├── B300              an attached battery
└── D1 Hub (HD1)      a DC hub
```

I plan to add a **B300K battery** and an **A1 hub** later. They will appear
automatically as new devices with the same entity shape, so **design the
battery and hub sections to repeat over however many exist** rather than
hardcoding two batteries and one hub. Use auto-entities or template-driven
cards if that helps; if you hardcode, tell me exactly what to change later.

## Entities

**Main unit — power flow (watts):** Solar Power, Grid Input Power, AC Output
Power, DC Output Power, Grid Feed-in Power, AC Load Power, DC Load Power

**Main unit — battery:** Battery (%), Charging Status, Battery Total Voltage,
Battery Total Current

**Main unit — grid & inverter:** Grid Frequency, Inverter Frequency,
Grid Import Energy (kWh), Grid Export Energy (kWh), PV Total Energy (kWh)

**Main unit — temperatures:** Ambient, Inverter, PV Converter

**Main unit — cells:** Cell Voltage Delta, Cell Voltage Min/Max (min/max are
disabled by default; enable them if you use them)

**Main unit — status:** Device Reachable, Cloud Connected, IoT Session,
and read-only state sensors: AC Output, DC Output, Solar Input, Grid Input

**Controls:** AC Output, DC Output, AC/DC ECO Mode, Grid Charging,
Grid Feed-in (switches); Charging Mode (select: standard / silent / turbo /
custom); AC/DC ECO Auto-Off (hours) and AC/DC ECO Power Threshold (watts)
(numbers)

**Per expansion (each battery):** Battery (%), Cell Balance (V), Temperature,
Cells, Voltage, Connection, Fault
**Per expansion (each hub):** Connection, Fault

## What I want

A dashboard I'd actually keep open. Priorities in order:

1. **At-a-glance energy flow** — where power is coming from and going to right
   now. A power-flow / energy-distribution card is ideal if a suitable one is
   available; otherwise build something equivalent. Prefer HACS cards only if
   they're already installed — check first, and fall back to built-in cards
   rather than telling me to install things.
2. **Battery health section** — one row per battery showing charge and
   **Cell Balance**. Cell Balance is the spread between the highest and lowest
   cell: mine sits around 0.002–0.005 V. It is the single best early warning of
   a failing cell, and the Bluetti app doesn't show it at all. Make it prominent
   and colour-code it: green under ~0.05 V, amber to ~0.1 V, red above.
3. **Controls**, clearly separated from readings so I can't hit a switch by
   accident while scanning values.
4. **Diagnostics**, tucked away — temperatures, frequencies, connection and
   fault sensors, per-expansion detail.

## Expected gaps — do not "fix" these

- **Per-battery Voltage and Temperature are unavailable at rest.** A pack only
  reports them under load. Leave them in place; they populate when charging or
  discharging.
- **Energy Today / This Month / This Year / Lifetime are unknown** on this
  hardware — the cloud endpoint returns no data. Use **Grid Import Energy**,
  **Grid Export Energy** and **PV Total Energy** for the Energy Dashboard
  instead, and don't put the unknown ones on the dashboard.
- **There is no state-of-health sensor**, deliberately. The device reports an
  implausible value, so it isn't surfaced. Use Cell Balance for health.
- Values update roughly every 10 seconds.

## Style

Dark-theme friendly, readable on both phone and desktop — assume I'll check it
on my phone most often, so the top of the view should carry the important
things. Use icons and colour meaningfully rather than decoratively. Group by
what I'd want to answer ("am I importing or exporting?", "are my batteries
healthy?"), not by entity type.

Show me the YAML and explain the layout choices. If something I asked for isn't
achievable with what's installed, say so and offer the closest alternative
rather than silently substituting.

## Also useful

Suggest two or three automations that this data makes possible — for example
alerting on a widening cell imbalance, on an expansion going offline, or on the
system switching to battery during a grid outage. Don't create them; just
propose them and I'll pick.
