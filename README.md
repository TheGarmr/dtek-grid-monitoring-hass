# dtek-grid-monitoring

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

[![hacs][hacsbadge]][hacs]
[![Project Maintenance][maintenance-shield]][user_profile]

Home Assistant custom integration that monitors real power outages at a DTEK
address. By default it does **not** poll DTEK constantly: monitoring starts only
when a sensor you choose (e.g. a grid/inverter binary sensor) reports that power
is gone, and stops when power comes back. Optionally it can also follow the
hourly outage schedule of the address (see
[Outage schedule monitoring](#outage-schedule-monitoring)).

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
| `sensor`        | Reason, type, start, expected restoration and timestamps; optionally today's and tomorrow's outage schedule and the next scheduled outage. |

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

### Voltage relay

If a voltage relay sits between the grid and the inverter, a voltage spike makes
it cut the grid off, and the inverter reports that grid power is gone even
though the city grid is fine. Point the integration at the relay's switch and
such trips are ignored: monitoring starts only if, 15 seconds after the source
sensor reports no power, the relay is not in its "tripped" state. During a real
outage a relay powered from the grid goes `unavailable` rather than `off`, so
it is still detected — including when a real outage follows a relay trip.

### Outage schedule monitoring

Off by default. When **Monitor outage schedules** is enabled, the integration
additionally asks DTEK every 15 minutes — regardless of the power state — for
the hourly outage schedule (the table shown on the shutdowns page). It reads
the schedule group(s) of your house from the same `getHomeNum` response,
exposes today's and tomorrow's outage windows and the start of the next
scheduled outage as sensors, and fires an event when the schedule for a day
appears or changes.

A house can belong to several groups (e.g. different entrances); every group
is reported separately. Only the published daily schedule is used, not the
weekly "possible outages" template.

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
| Voltage relay | Optional switch of a voltage relay between the grid and the inverter | — |
| Relay state meaning "tripped" | Relay state that means it cut the grid off itself | `off` |
| Monitor outage schedules | Poll the hourly outage schedule every 15 minutes | off |

City and street are matched against DTEK's own list, so the apostrophe style
(`'` vs `’`), letter case and extra spaces do not matter; the type prefix
(`м.`, `вул.`, …) is still required.

The address is validated against DTEK when you submit the form. Polling
intervals, the voltage relay and schedule monitoring are adjustable later via
the integration's **Configure** dialog. Add
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
| Schedule today | sensor (enum) | `scheduled` / `no_outages` / `not_published` — whether DTEK scheduled outages for today. Only with schedule monitoring enabled |
| Schedule tomorrow | sensor (enum) | The same for tomorrow |
| Next scheduled outage | sensor (timestamp) | Start of the nearest scheduled outage that has not begun yet, across all groups of the house. Attributes: `end`, `summary` (e.g. `20:00–01:00`), `group`, `name`, `type`. Windows that continue past midnight count as one outage. Moves on to the following outage at the next check, up to 15 minutes after the current one starts |

The schedule sensors carry these attributes:

| Attribute | Meaning |
| --- | --- |
| `date` | The day the schedule is for, `YYYY-MM-DD` |
| `summary` | Ready-to-send text, one line per group, e.g. `Черга 2.1: 00:00–01:00, 20:00–24:00`. Possible (not confirmed) windows are prefixed with `~`. Empty when there are no outages |
| `groups` | List of `{group, name, intervals}`; each interval is `{start, end, type}` with `HH:MM` times and type `outage` or `possible` |
| `updated` | When DTEK last updated the schedule |

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
| `dtek_grid_monitoring_schedule_available` | The outage schedule for a day is published for the first time |
| `dtek_grid_monitoring_schedule_changed` | An already known schedule for today or a later day changes or is withdrawn |

Common event data: `entry_id`, `name`, `city`, `street`, `houses`. The schedule
events also include `expected_restore_at`, `expected_restore_raw`, `reason`,
`outage_kind`. The restored event includes `restored_at`, `down_since`,
`duration_minutes`.

The schedule events include `date`, `day` (`today` / `tomorrow` / `later`),
`has_outages`, `summary`, `groups` and `updated` — the same shape as the sensor
attributes; `schedule_changed` also carries `previous_summary`. They are fired
only for changes seen while Home Assistant is running: the first check after a
start just records the current schedule.

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

A morning summary that is sent only when outages are scheduled, plus a
notification whenever today's schedule changes (replace the entity id with
your own):

```yaml
automation:
  - alias: Morning DTEK outage schedule
    trigger:
      - platform: time
        at: "07:30:00"
    condition:
      - condition: state
        entity_id: sensor.home_schedule_today
        state: scheduled
    action:
      - service: notify.mobile_app_phone
        data:
          title: Outages today
          message: "{{ state_attr('sensor.home_schedule_today', 'summary') }}"

  - alias: DTEK outage schedule for today changed
    trigger:
      - platform: event
        event_type: dtek_grid_monitoring_schedule_changed
        event_data:
          day: today
    action:
      - service: notify.mobile_app_phone
        data:
          title: "{{ trigger.event.data.name }}: schedule changed"
          message: "{{ trigger.event.data.summary or 'No outages today' }}"

  - alias: DTEK scheduled outage in 30 minutes
    trigger:
      - platform: time
        at:
          entity_id: sensor.home_next_scheduled_outage
          offset: "-00:30:00"
    action:
      - service: notify.mobile_app_phone
        data:
          title: Power outage in 30 minutes
          message: >
            {{ state_attr('sensor.home_next_scheduled_outage', 'name') }}:
            {{ state_attr('sensor.home_next_scheduled_outage', 'summary') }}
```

## Notes

- Requires no extra Python packages; uses Home Assistant's bundled `aiohttp`.
- The DTEK site is behind Incapsula; access works over plain HTTP with a normal
  cookie jar, so no headless browser is needed.
- All DTEK dates are in Europe/Kyiv and exposed as timezone-aware timestamps.
- A failed DTEK request does not make the entities unavailable: power state
  comes from the source sensor, DTEK sensors keep their last known values, and
  **Last checked** shows when DTEK last answered.

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
