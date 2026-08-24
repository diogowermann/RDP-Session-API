# RDP Session API documentation

This directory contains the public technical documentation for RDP Session API.

## Main documents

- [Installation and configuration](installation.md) — initial Linux setup, database, systemd, HTTPS, Windows server registration, Grafana, upgrades and troubleshooting.
- [System architecture](system-architecture.md) — context, trust boundaries, internal components, data model, ingestion/reconciliation flows and session state machine.
- [Grafana logon alerting](grafana-alerting.md) — cross-server LOGON event feed, Infinity query setup, multi-dimensional alert instances, no-data behavior and notification templates.
- [systemd operations](systemd.md) — managed Linux runtime, service status, journald, upgrades and migration from manual Uvicorn execution.

## Companion project

Windows collection is implemented by [RDP-Session-Agent](https://github.com/diogowermann/RDP-Session-Agent).

## Public documentation policy

Examples in this repository must remain infrastructure-agnostic. Do not add real credentials, internal DNS names, private IP addresses, TLS private material, or company-specific production configuration.
