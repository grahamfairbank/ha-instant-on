# Changelog

All notable changes to this project are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-10-17

### Added
- A built-in **Network** sidebar panel that shows the card full-screen. Users no longer need to create a dashboard. Turn it off with the
  new **Show the Network panel in the sidebar** option.
- README steps for adding the card to your own dashboard.
- `tools/card-preview/panel.html` for previewing the panel.
- **Internet health**: latency, jitter, packet loss, DNS and HTTPS checks every 30 s, public IP and Cloudflare location, scheduled
  Cloudflare speed tests with a **Run speed test** button, and a new *Internet* device with these sensors.
- The card's new `internet` section: status, stat tiles, uptime (24 h / 7 d), 24 h latency chart, 7-day hourly status strip and
  speed test history.
- The Home Assistant host's own network link (speed, and Ethernet, Wi-Fi or virtual) is reported, and the card warns when it limits speed tests.
- Options: **Monitor internet health**, **Run a speed test every (hours)**.

## [0.2.0] - 2026-10-16

### Added
- `custom:instant-on-card`: a mission-control dashboard card served by the integration (no separate install), with a network map,
  health and client rings, 24 h throughput, PoE budget, AP radio panels, switch port grids and top talkers.
- `instant_on/overview` websocket command that feeds the card.
- Sensors: site download and upload throughput, per-device client count, AP channel utilization, switch PoE power.

### Changed
- APs and switches are linked to their site device by device ID. The previous `via_device` method is deprecated and stops
  working in Home Assistant 2027.8.

### Fixed
- Wired clients behind the same switch port report that port's traffic, so throughput now counts each port once.
- The card showed "Configuration error" in Home Assistant. The integration loads the card before Home Assistant installs its own
  custom element registry, so the card now waits for the Home Assistant app to load before registering.
- Map nodes and radio labels are wider, to fit Home Assistant's font.

## [0.1.0] - 2026-10-16

### Added
- First release: UI setup with site selection, re-authentication and options (poll interval, client tracking).
- Per-site sensors: clients, wireless clients, wired clients, network devices, active alerts, health score.
- Connectivity binary sensor for each AP and switch.
- Device tracker for each client (disabled by default), with the connected AP or switch port.
- Diagnostics with personal data redacted.
- Hostnames and the OAuth client ID are read from the portal's `settings.json` instead of being hard-coded.

### Notes
- Tested against a live site with AP-505 access points and JL681A/JL684A switches (firmware 3.4.2).
