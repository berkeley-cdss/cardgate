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

1. **Obtain API credentials**: You will need to obtain API credentials for the following UC Berkeley SIS services. Contact your departmental SIS support for access.
   - `SIS_TERMS_ID` / `SIS_TERMS_KEY`
   - `SIS_CLASSES_ID` / `SIS_CLASSES_KEY`
   - `SIS_ENROLLMENTS_ID` / `SIS_ENROLLMENTS_KEY`
   - `SIS_STUDENTS_ID` / `SIS_STUDENTS_KEY` (optional, for SIS to CalNet UID conversion)

2. **Configure environment variables**: Create a `.env` file in your working directory with these credentials:

   ```bash
   SIS_TERMS_ID=your_terms_id
   SIS_TERMS_KEY=your_terms_key
   SIS_CLASSES_ID=your_classes_id
   SIS_CLASSES_KEY=your_classes_key
   SIS_ENROLLMENTS_ID=your_enrollments_id
   SIS_ENROLLMENTS_KEY=your_enrollments_key
   SIS_STUDENTS_ID=your_students_id
   SIS_STUDENTS_KEY=your_students_key
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
| SID/EID Number | Student ID (SIS) or Employee ID (HR) |
| Prox Number | Left blank (populated by Card Key API in Phase 2) |
| Type of Card | Left blank |
| Action | "Add" |
| Clearance Name | Mapped from the person's role (e.g., Course-enrolled, Course-staff, Faculty, etc.) |
| Activation Date | Left blank |
| Clearance Name | (Spare) |
| Activation Date | (Spare) |
| Clearance Name | (Spare) |
| Activation Date | (Spare) |
| Clearance Name | (Spare) |
| Activation Date | (Spare) |
| Clearance Name | (Spare) |
| Activation Date | (Spare) |

The role mapping is defined in `access_config.yaml`. The spare clearance columns are available for multi-location requests.
