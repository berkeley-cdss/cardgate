---
title: Card Gate
---

This application is used to generate card key data that can be received by UC Berkeley's Facilities. The data is populated in their "Facilities Services Electronic Access Control Card Key Request" template. The app can be run as a CLI tool or via a web UI.

## Installation

Install directly from the GitHub repository:

```bash
pip install git+https://github.com/berkeley-cdss/cardgate.git
```

## Setup

See [Setup](setup.md) for setup instructions, including API credentials, `cardgate.yaml` configuration, and environment variables.

## Quick Start (CLI)

Generate card key requests for all Statistics Department courses in the Gateway building for Fall 2026:

```bash
cardgate courses \
    --unit STAT --building Gateway \
    --year 2026 --semester Fall \
    --output stat-gateway-2026-fall.csv
```

To only include evening sections (starting at 6:00 PM or later):

```bash
cardgate courses \
    --unit STAT --building Gateway \
    --year 2026 --semester Fall \
    --from-time 18:00 \
    --output stat-evening-2026-fall.csv
```

To restrict which clearance columns appear:

```bash
cardgate courses \
    --unit STAT --building Gateway \
    --year 2026 --semester Fall \
    --clearances "Gateway Exterior Door,Gateway Classroom" \
    --output stat-gateway-limited.csv
```

All three subcommands (`courses`, `employees`, `programs`) accept `--clearances` and `--config`.

## CSV Output

The CSV output is formatted to match the "Facilities Services Electronic Access Control Card Key Request" template. The columns are:

| Column | Description |
|-------|-------------|
| Date Submitted | Left blank for the requestor to fill in |
| Last Name | Person's last name |
| First Name | Person's first name |
| MI | Middle initial (if available) |
| Department | Academic unit passed via `--unit` |
| Student/Employee ID Number | Student ID (SID) or Employee ID |
| 6 digit (Low Frequency) | Low-frequency prox number (from Cal1Card API) |
| 7 digit (High Frequency) | High-frequency SEOS number (from Cal1Card API) |
| Type of Card | "CalID" |
| Action | "Add Clearance" |
| Clearance Name | Location from `cardgate.yaml` (up to 10 columns; unfilled columns are empty) |
