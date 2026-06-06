---
title: Set Up
---

## API Credentials

You will need credentials for the following services.

- **SIS** (course and enrollment data)
  - `SIS_TERMS_ID` / `SIS_TERMS_KEY`
  - `SIS_CLASSES_ID` / `SIS_CLASSES_KEY`
  - `SIS_ENROLLMENTS_ID` / `SIS_ENROLLMENTS_KEY`
- **Cal1Card** (card key numbers — production only; test defaults are built in)
  - `C1C_APP_ID` / `C1C_APP_KEY`
  - `C1C_API_BASE_URL` (optional; defaults to the test endpoint)
- **CalNet OIDC** (web app authentication — optional for local dev, required for deployment)
  - `CLIENT_ID` / `CLIENT_SECRET` — CalNet OIDC client credentials
  - `CALNET_ENVIRONMENT` — `test` or `prod` (defaults to `prod`)
  - `SECRET_KEY` — Flask session signing key (generate a random value)
  - `BASE_URL` — public URL of the deployed app

## Configuration

Create a `cardgate.yaml` file in your working directory:

```yaml
clearances:
  - Gateway Exterior Door
  - Gateway Classroom
  - Gateway L1 West

# Web frontend configuration (dropdowns)
web:
  academic_units:
    - STAT
    - COMPSCI
    - EECS
    - CDSS
    - Other
  buildings:
    - Gateway
    - Evans
    - Other
  semesters:
    - spring
    - summer
    - fall
```

The `clearances` list defines the clearance location names that appear in the CSV output columns and in the web UI multi-select. The `web` section configures the dropdown options in the web form; use `Other` to allow free-text entry.

## Environment Variables

Create a `.env` file in your working directory:

```bash
# SIS credentials
SIS_TERMS_ID=your_terms_id
SIS_TERMS_KEY=your_terms_key
SIS_CLASSES_ID=your_classes_id
SIS_CLASSES_KEY=your_classes_key
SIS_ENROLLMENTS_ID=your_enrollments_id
SIS_ENROLLMENTS_KEY=your_enrollments_key

# Cal1Card credentials (omit C1C_API_BASE_URL for the test endpoint)
C1C_APP_ID=your_app_id
C1C_APP_KEY=your_app_key
C1C_API_BASE_URL=https://your-production-endpoint.berkeley.edu

# CalNet OIDC (omit for local development — web app runs without authentication)
# CLIENT_ID=your_calnet_oidc_client_id
# CLIENT_SECRET=your_calnet_oidc_client_secret
# CALNET_ENVIRONMENT=prod
# SECRET_KEY=<generate-a-random-key>
# BASE_URL=https://your-deployment.example.com
```

Both the CLI and the web app load this file automatically.

## Running the Web App Locally

```bash
python3 cardgate/webapp.py
```

Open `http://localhost:5000` in a browser. If `CLIENT_ID` and `CLIENT_SECRET` are not set, the web app runs without authentication for local development. When OIDC is configured, all routes except the login page require CalNet authentication.

The web app provides the same functionality as the CLI through a browser form. See [Web Application](web.md) for full details on form fields, output, and configuration.
