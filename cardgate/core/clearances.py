import yaml
from pathlib import Path
from typing import List, Optional
def load_cardgate_config(config_path: str = "cardgate.yaml") -> dict:
    """
    Loads the YAML configuration file defining clearance locations and date buffers.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found at: {config_path}")

    with open(path, "r") as f:
        return yaml.safe_load(f)


def get_clearance_locations(config: dict) -> List[str]:
    """Returns the list of clearance location names."""
    return config.get("clearances", [])


def get_academic_units(config: dict) -> list:
    """Returns the list of academic units for the web dropdown.
    'Other' is always appended as an implicit choice.
    """
    web_config = config.get("web", {})
    units = list(web_config.get("academic_units", []))
    units.append("Other")
    return units


def get_semesters(config: dict) -> List[str]:
    """Returns the list of semester options for the web dropdown."""
    web_config = config.get("web", {})
    return web_config.get("semesters", ["spring", "summer", "fall"])


def get_buildings(config: dict) -> list:
    """Returns the list of building codes for the web dropdown.
    'Other' is always appended as an implicit choice.
    """
    web_config = config.get("web", {})
    bldgs = list(web_config.get("buildings", []))
    bldgs.append("Other")
    return bldgs


def get_hr_department_codes(config: dict) -> list:
    """Returns the list of HR department codes for the employees multi-select.
    Custom codes can be entered via the separate text input.
    """
    web_config = config.get("web", {})
    return list(web_config.get("hr_department_codes", []))


def get_allowed_groups(config: dict) -> List[str]:
    """Returns the list of allowed Grouper paths for web app access."""
    web_config = config.get("web", {})
    return web_config.get("allowed_groups", [])


def get_hr_job_title_groups(config: dict) -> dict:
    """Returns the HR job title code groups defined at the top level of config.

    Each group is a mapping with 'label' and 'codes' keys, e.g.:
      gsi_ta: {label: "GSIs / TAs (incl. UGSI)", codes: ["002320", "002321"]}
    """
    return config.get("hr_job_title_codes", {}) or {}


def resolve_hr_job_title_codes(
    config: dict,
    group_keys: Optional[List[str]] = None,
    extra_codes: Optional[List[str]] = None,
) -> Optional[List[str]]:
    """Resolve selected group keys plus explicit codes into a list of
    zero-padded title codes. Returns None when nothing is selected,
    meaning no job-code filtering should be applied.
    """
    groups = get_hr_job_title_groups(config)
    resolved: List[str] = []

    for key in group_keys or []:
        group = groups.get(key) or {}
        resolved.extend(group.get("codes", []))

    for code in extra_codes or []:
        code = str(code).strip()
        if code:
            resolved.append(code)

    if not resolved:
        return None

    # Dedupe, preserve order, normalize to six digits
    seen = set()
    normalized = []
    for c in resolved:
        padded = str(c).zfill(6)
        if padded not in seen:
            seen.add(padded)
            normalized.append(padded)
    return normalized
