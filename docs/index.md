---
title: Card Gate
---

This application is used to generate card key data that can be received by UC Berkeley's Facilities. The data is populated in their "Facilities Services Electronic Access Control Card Key Request" template. The app can be run as a CLI tool.

## Installation

Install directly from the GitHub repository:

```bash
pip install git+https://github.com/berkeley-cdss/cardgate.git
```

## Setup

1. **Obtain API credentials**: You will need to obtain API credentials for the following UC Berkeley SIS services.

   - `SIS_TERMS_ID` / `SIS_TERMS_KEY`
   - `SIS_CLASSES_ID` / `SIS_CLASSES_KEY`
   - `SIS_ENROLLMENTS_ID` / `SIS_ENROLLMENTS_KEY`

2. **Configure the application**: Create a `cardgate.yaml` configuration file:

```yaml
clearances:
  - Gateway Exterior Door
  - Gateway Classroom
  - Gateway L1 West

# Buffer days to add to term dates for activation/expiration
# Negative values mean before the date, positive means after it
date_buffer:
  activation_days: -7   # 7 days before semester starts
  expiration_days: 4    # 4 days after semester ends
```

3. **Configure environment variables**: Create a `.env` file in your working directory with these credentials:

```bash
SIS_TERMS_ID=your_terms_id
SIS_TERMS_KEY=your_terms_key
SIS_CLASSES_ID=your_classes_id
SIS_CLASSES_KEY=your_classes_key
SIS_ENROLLMENTS_ID=your_enrollments_id
SIS_ENROLLMENTS_KEY=your_enrollments_key
```

## Quick Start

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

## CSV Output

The CSV output is formatted to match the "Facilities Services Electronic Access Control Card Key Request" template. The columns are:

| Column | Description |
|-------|-------------|
| Date Submitted | Left blank for the requestor to fill in |
| Last Name | Person's last name |
| First Name | Person's first name |
| MI | Middle initial (if available) |
| Department | Academic unit passed via `--unit` |
| SID/EID Number | Student ID or Employee ID |
| Prox Number | Left blank (populated by Card Key API in Phase 2) |
| Type of Card | "CalID" |
| Action | "Add Clearance" |
| Clearance Name | Location from `cardgate.yaml` |
| Activation Date | Term begin date + buffer |
|Expiration Date | Term end date + buffer |

The remaining clearance columns are repeated for each location defined in `clearances`.
