# HydroQ

Commercial hydroponic zone control for Home Assistant + ESPHome.

## Requirements

- Home Assistant **2024.1** or newer
- ESPHome controller flashed with HydroQ firmware (`hydroq-controller-FULL.yaml`)
- HACS **Frontend** cards (install before opening the HydroQ dashboard):

| Card | HACS name |
|------|-----------|
| Mushroom Cards | `Mushroom` |
| Bubble Card | `Bubble Card` |
| Mini Graph Card | `mini-graph-card` |
| Vertical Stack In Card | `Vertical Stack In Card` |

Optional: **Graphite Auto** theme (Home view uses it when installed).

## Features

- Auto Lovelace operator dashboard (`/hydroq`)
- Irrigation schedule (5 slots), Auto Irrigation, Semi/Full-Auto modes
- Nutrient dosing (A → B), neutralize, pH up/down, Balance command
- Grow-light control (controller + WiFi relay kit, stands 1–12)
- Growth-stage recipes, calibration wizard, health score + notifications
- Multi-zone: add one config entry per controller board

## Setup

1. Flash ESPHome firmware and confirm the device is online in HA.
2. Install this integration (HACS or manual copy).
3. **Settings → Devices & services → Add integration → HydroQ**
4. Map hardware preset, entities, reservoir volume, confirm HACS cards.
5. Open sidebar **HydroQ** (or call `hydroq.create_dashboard`).

Disable legacy zone automations/scripts if migrating from YAML — HydroQ replaces them.

## Support

- Docs: [Quick Start](https://github.com/hydroq/hydroq/blob/main/docs/QUICK_START.md)
- Issues: [GitHub Issues](https://github.com/hydroq/hydroq/issues)
