import yaml
from pathlib import Path

def load_config(config_path: str = "access_config.yaml") -> dict:
    """
    Loads the YAML configuration file defining access categories.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found at: {config_path}")
    
    with open(path, "r") as f:
        return yaml.safe_load(f)
