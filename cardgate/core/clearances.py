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
