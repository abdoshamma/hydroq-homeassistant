# HydroQ — Home Assistant integration

HydroQ custom integration for Home Assistant (HACS).

## Install via HACS (one click)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=abdoshamma&repository=hydroq-homeassistant&category=integration)

1. Click the button above → choose your Home Assistant instance → **Add** / open in HACS.
2. **Download** HydroQ in HACS.
3. Restart Home Assistant.
4. **Settings → Devices & services → Add integration → HydroQ**

### Manual custom repository (if the button fails)

1. Install [HACS](https://hacs.xyz/) if needed.
2. **HACS → Integrations → ⋮ → Custom repositories**
3. URL: `https://github.com/abdoshamma/hydroq-homeassistant`
4. Category: **Integration** → Add → Download HydroQ → Restart HA.

Install the required Lovelace cards (Mushroom, Bubble Card, Mini Graph, Vertical Stack In Card) **before** opening the HydroQ dashboard.

## Manual install (zip)

Download the release zip, extract into your HA `/config` folder so you have:

```text
/config/custom_components/hydroq/
```

Restart HA, then add the integration.

## ESPHome firmware

Firmware is **not** included in this repo. Flash from the product project:

- `esphome/devices/hydroq-controller-FULL.yaml`
