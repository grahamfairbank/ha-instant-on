# Changelog

All notable changes to this project are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
