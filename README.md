# HydroQ — Home Assistant integration

HACS repository root for the HydroQ custom integration.

## Install via HACS

1. Install [HACS](https://hacs.xyz/) if needed.
2. **HACS → Integrations → ⋮ → Custom repositories**
3. Add this repository URL, category **Integration**.
4. **HACS → Integrations → HydroQ → Download**
5. Restart Home Assistant.
6. **Settings → Devices & services → Add integration → HydroQ**

Install the required Lovelace cards (Mushroom, Bubble Card, Mini Graph, Vertical Stack In Card) **before** opening the HydroQ dashboard.

## Manual install

Download the release zip, extract into your HA `/config` folder so you have:

```text
/config/custom_components/hydroq/
```

Restart HA, then add the integration.

## ESPHome firmware

Firmware is **not** included in this repo package. Use the main HydroQ product repo:

- `esphome/devices/hydroq-controller-FULL.yaml`

## Documentation

- [Quick Start](https://github.com/hydroq/hydroq/blob/main/docs/QUICK_START.md)
- [Install checklist](https://github.com/hydroq/hydroq/blob/main/docs/INSTALL.md)
