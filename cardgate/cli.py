import os
import typer
import logging
import sys
from typing import List, Optional
from dotenv import load_dotenv

from cardgate.core.pipeline import (
    fetch_employees,
    fetch_program_students,
    fetch_course_people,
    fetch_card_data,
    export_to_csv,
    get_programs,
)
from cardgate.core.clearances import load_cardgate_config

# Configure logging to write to stderr
logging.basicConfig(
    level=logging.INFO, format="%(levelname)s: %(message)s", stream=sys.stderr
)
logger = logging.getLogger(__name__)

# Load environment variables from .env
load_dotenv()

app = typer.Typer(
    help="Card Key Data Generation CLI",
    rich_markup_mode=None,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.command()
def courses(
    academic_unit: str = typer.Option(
        ..., "--unit", help="Academic unit or department code (e.g., STAT)"
    ),
    building: str = typer.Option(
        ..., "--building", help="Building name to filter courses (e.g., Evans)"
    ),
    year: Optional[int] = typer.Option(
        None,
        "--year",
        help="Course year, e.g. 2026. Defaults to current term if omitted.",
    ),
    semester: Optional[str] = typer.Option(
        None,
        "--semester",
        help="Semester: spring, summer, fall. Defaults to current term if omitted.",
    ),
    from_time: Optional[str] = typer.Option(
        None,
        "--from-time",
        help="Only include sections starting at or after this time (24h format, e.g., 18:00)",
    ),
    output_file: Optional[str] = typer.Option(
        None, "--output", "-o", help="Output CSV file path. Defaults to stdout."
    ),
    clearances: Optional[str] = typer.Option(
        None,
        "--clearances",
        help="Comma-separated clearance names (defaults to all from config)",
    ),
    config_file: str = typer.Option(
        os.environ.get("CARDGATE_CONFIG", "cardgate.yaml"),
        "--config",
        "-c",
        help="Path to config YAML (default: CARDGATE_CONFIG env var or cardgate.yaml)",
    ),
):
    """
    Generate card key access spreadsheets for course-enrolled students and course-staff in a specific building.
    """
    logger.info(f"Starting pipeline for courses...")
    people = fetch_course_people(academic_unit, building, year, semester, from_time)

    if not os.path.exists(config_file):
        logger.warning(f"Config file not found: {config_file}")
        config_file = None

    if people:
        fetch_card_data(people)

    export_to_csv(
        people,
        academic_unit,
        output_path=output_file,
        config_path=config_file,
        clearances=clearances.split(",") if clearances else None,
    )


@app.command()
def employees(
    hr_dept: str = typer.Option(
        ..., "--hr-dept", help="HR department code (e.g., PSTAT)"
    ),
    output_file: Optional[str] = typer.Option(
        None, "--output", "-o", help="Output CSV file path. Defaults to stdout."
    ),
    clearances: Optional[str] = typer.Option(
        None,
        "--clearances",
        help="Comma-separated clearance names (defaults to all from config)",
    ),
    config_file: str = typer.Option(
        os.environ.get("CARDGATE_CONFIG", "cardgate.yaml"),
        "--config",
        "-c",
        help="Path to config YAML (default: CARDGATE_CONFIG env var or cardgate.yaml)",
    ),
):
    """
    Generate card key access spreadsheets for employees in an HR department.
    """
    logger.info(f"Starting pipeline for employees...")
    people = fetch_employees([hr_dept])
    if people:
        fetch_card_data(people)
    export_to_csv(
        people,
        hr_dept,
        config_file,
        output_path=output_file,
        clearances=clearances.split(",") if clearances else None,
    )


@app.command()
def programs(
    academic_unit: str = typer.Option(
        ..., "--unit", help="Academic unit or department code (e.g., STAT)"
    ),
    program_codes: List[str] = typer.Option(
        ..., "--program-code", help="Program codes for the unit (can specify multiple)"
    ),
    output_file: Optional[str] = typer.Option(
        None, "--output", "-o", help="Output CSV file path. Defaults to stdout."
    ),
    clearances: Optional[str] = typer.Option(
        None,
        "--clearances",
        help="Comma-separated clearance names (defaults to all from config)",
    ),
    config_file: str = typer.Option(
        os.environ.get("CARDGATE_CONFIG", "cardgate.yaml"),
        "--config",
        "-c",
        help="Path to config YAML (default: CARDGATE_CONFIG env var or cardgate.yaml)",
    ),
):
    """
    Generate card key access spreadsheets for program-enrolled students (PhD, MA, BA).
    """
    logger.info(f"Starting pipeline for program students...")

    # Build code_to_role mapping from config
    code_to_role = {}
    if config_file and os.path.exists(config_file):
        cfg = load_cardgate_config(config_file)
        for prog in get_programs(cfg):
            if prog.get("code"):
                code_to_role[prog["code"]] = prog.get("role", "Program-enrolled")

    people = fetch_program_students(program_codes, code_to_role=code_to_role)
    if people:
        fetch_card_data(people)
    export_to_csv(
        people,
        academic_unit,
        config_file,
        output_path=output_file,
        clearances=clearances.split(",") if clearances else None,
    )


if __name__ == "__main__":
    app()
