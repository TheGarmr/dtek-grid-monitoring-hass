# dtek-grid-monitoring

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

[![hacs][hacsbadge]][hacs]
[![Project Maintenance][maintenance-shield]][user_profile]

Home Assistant custom integration that monitors real power outages at a DTEK
address. It does **not** poll DTEK constantly: monitoring starts only when a
sensor you choose (e.g. a grid/inverter binary sensor) reports that power is
gone, and stops when power comes back.

[![Add Integration to Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=dtek_grid_monitoring)

While an outage is active, the integration queries the DTEK shutdowns site,
finds the relevant record for your address, exposes it as Home Assistant
entities, and fires events you can use to build your own notifications — in
Telegram, mobile push, or anything else Home Assistant can notify. There is no
`ntfy` and no built-in Telegram: notifications are entirely up to your Home
Assistant automations. Available in English, Ukrainian and Russian.

![example][exampleimg]

**This component sets up the following platforms:**

| Platform        | Description                            |
| --------------- | -------------------------------------- |
| `binary_sensor` | On while an outage is being monitored. |
| `sensor`        | Reason, type, start, expected restoration and timestamps. |

## How it works

1. You configure one DTEK address (city / street / house numbers) and a **power
   source sensor** (default `binary_sensor.deye_grid`).
2. When the source sensor switches to the "no power" state (default `off`),
   monitoring begins.
3. The integration loads the DTEK shutdowns page, reads the CSRF token and
   session cookie, and calls the site's `getHomeNum` AJAX endpoint for your
   city/street over plain HTTP.
4. Among your house numbers it picks the best matching record (a relevant
   scheduled/emergency/planned outage; if several match, the one with the
   earliest expected restoration).
5. It polls quickly (default every 2 min) until DTEK has information, then
   slower (default every 10 min). Entities update on every check.
6. When the source sensor returns to the "power on" state, monitoring stops and
   a restoration event is fired.

## Installation

### HACS (custom repository)

1. HACS → Integrations → ⋮ → **Custom repositories**.
2. Add `https://github.com/TheGarmr/dtek-grid-monitoring`, category
   **Integration**.
3. Install **DTEK Grid Monitoring**, then restart Home Assistant.

### Manual

Copy `custom_components/dtek_grid_monitoring` into your Home Assistant
`config/custom_components/` directory and restart.

## Configuration

Add the integration via **Settings → Devices & Services → Add Integration →
DTEK Grid Monitoring**. You will be asked for:

| Field | Description | Default |
| --- | --- | --- |
| Name | Friendly name for this address/device | — |
| DTEK shutdowns page URL | The DTEK region page | `https://www.dtek-oem.com.ua/ua/shutdowns` |
| City | As written on the DTEK site, e.g. `м. Одеса` | — |
| Street | As written on the DTEK site | — |
| House number(s) | Comma-separated, e.g. `9` or `33А, 33/А` | — |
| Power source sensor | Entity that reports power presence | `binary_sensor.deye_grid` |
| State meaning "no power" | Source-sensor state that triggers monitoring | `off` |

The address is validated against DTEK when you submit the form. Polling
intervals are adjustable later via the integration's **Configure** dialog. Add
another address by adding the integration again — one address + one source
sensor per entry.

## Entities

Each configured address creates a device with:

| Entity | Type | Meaning |
| --- | --- | --- |
| Grid power | binary_sensor (`power`) | **On = power present, Off = outage.** The simple "is there light" indicator, and the cleanest thing to trigger automations on. |
| Power status | sensor (enum) | `power_on` / `outage_no_info` / `outage_with_info` — same idea, but also tells you whether DTEK has data yet |
| Outage reason | sensor | DTEK `sub_type` text |
| Outage type | sensor (enum) | `planned` / `scheduled` / `emergency` / `unknown` |
| Outage start | sensor (timestamp) | DTEK outage start |
| Expected restoration | sensor (timestamp) | DTEK expected `end_date` |
| DTEK updated | sensor (timestamp) | When DTEK last refreshed the record |
| Last checked | sensor (timestamp) | Last poll by the integration (disabled by default) |

## Events (for notifications)

For automations, prefer these two approaches over the generic device triggers:
a **State** trigger on the **Grid power** entity (`on → off` = power lost,
`off → on` = restored), or — for richer notifications carrying reason and
restoration time — the events below.

The integration fires these events on the Home Assistant bus. Build automations
that listen for them and send notifications however you like.

| Event | Fired when |
| --- | --- |
| `dtek_grid_monitoring_outage_started` | Source sensor reports power lost |
| `dtek_grid_monitoring_info_available` | A restoration schedule / expected time first appears |
| `dtek_grid_monitoring_restore_rescheduled` | Expected restoration time changes |
| `dtek_grid_monitoring_restored` | Source sensor reports power restored |

Common event data: `entry_id`, `name`, `city`, `street`, `houses`. The schedule
events also include `expected_restore_at`, `expected_restore_raw`, `reason`,
`outage_kind`. The restored event includes `restored_at`, `down_since`,
`duration_minutes`.

### Example automation

```yaml
automation:
  - alias: Notify when DTEK restoration time appears
    trigger:
      - platform: event
        event_type: dtek_grid_monitoring_info_available
    action:
      - service: notify.mobile_app_phone
        data:
          title: "{{ trigger.event.data.name }}"
          message: >
            Restoration expected at {{ trigger.event.data.expected_restore_raw }}
            ({{ trigger.event.data.reason }}).
```

## Notes

- Requires no extra Python packages; uses Home Assistant's bundled `aiohttp`.
- The DTEK site is behind Incapsula; access works over plain HTTP with a normal
  cookie jar, so no headless browser is needed.
- All DTEK dates are in Europe/Kyiv and exposed as timezone-aware timestamps.

## License

MIT © TheGarmr

[releases-shield]: https://img.shields.io/github/release/TheGarmr/dtek-grid-monitoring.svg?style=for-the-badge
[releases]: https://github.com/TheGarmr/dtek-grid-monitoring/releases
[commits-shield]: https://img.shields.io/github/commit-activity/y/TheGarmr/dtek-grid-monitoring.svg?style=for-the-badge
[commits]: https://github.com/TheGarmr/dtek-grid-monitoring/commits/main
[license-shield]: https://img.shields.io/github/license/TheGarmr/dtek-grid-monitoring.svg?style=for-the-badge
[hacs]: https://hacs.xyz
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-%40TheGarmr-blue.svg?style=for-the-badge
[user_profile]: https://github.com/TheGarmr
[exampleimg]: banner.png
