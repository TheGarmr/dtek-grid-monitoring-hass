[![GitHub Release][releases-shield]][releases]
[![License][license-shield]](LICENSE)
[![hacs][hacsbadge]][hacs]

Monitor real power outages at a DTEK address, driven by a Home Assistant
sensor. Polling starts only when your grid sensor reports that power is gone,
and stops when it returns.

**This component sets up the following platforms:**

| Platform        | Description                                            |
| --------------- | ------------------------------------------------------ |
| `binary_sensor` | On while an outage is being monitored.                 |
| `sensor`        | Reason, type, start, expected restoration, timestamps. |

![example][exampleimg]

{% if not installed %}

## Installation

1. Click install.
2. In the HA UI go to "Settings" -> "Devices & Services", click "+ Add
   Integration" and search for "DTEK Grid Monitoring".

{% endif %}

## Configuration is done in the UI

You provide a DTEK address (city / street / house numbers) and the sensor that
reports whether that address has power. Notifications are up to your own Home
Assistant automations, triggered by the events the integration fires.

Available in English, Ukrainian and Russian.

[releases-shield]: https://img.shields.io/github/release/TheGarmr/dtek-grid-monitoring.svg?style=for-the-badge
[releases]: https://github.com/TheGarmr/dtek-grid-monitoring/releases
[license-shield]: https://img.shields.io/github/license/TheGarmr/dtek-grid-monitoring.svg?style=for-the-badge
[hacs]: https://hacs.xyz
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[exampleimg]: banner.png
