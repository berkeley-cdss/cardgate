import asyncio
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
    export_to_csv,
)
from cardgate.integrations.sis import get_term_dates
from sis.terms import get_term_id_from_year_sem

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
    context_settings={"help_option_names": ["-h", "--help"]}
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
    config_file: Optional[str] = typer.Option(
        "cardgate.yaml",
        "--config",
        "-c",
        help="Path to config YAML",
    ),
):
    """
    Generate card key access spreadsheets for course-enrolled students and course-staff in a specific building.
    """
    logger.info(f"Starting pipeline for courses...")
    people = fetch_course_people(academic_unit, building, year, semester, from_time)

    term_begin = None
    term_end = None

    if year and semester:
        terms_id = os.getenv("SIS_TERMS_ID")
        terms_key = os.getenv("SIS_TERMS_KEY")
        if terms_id and terms_key:
            term_id = asyncio.run(
                get_term_id_from_year_sem(terms_id, terms_key, year, semester.lower())
            )
            term_begin, term_end = asyncio.run(get_term_dates(term_id))
            if term_begin:
                logger.info(f"Term dates: {term_begin} to {term_end}")
            else:
                logger.warning(f"Could not fetch term dates for {term_id}")

    if not os.path.exists(config_file):
        logger.warning(f"Config file not found: {config_file}")
        config_file = None

    export_to_csv(
        people,
        academic_unit,
        output_path=output_file,
        term_begin=term_begin,
        term_end=term_end,
        config_path=config_file,
    )


@app.command()
def employees(
    academic_unit: str = typer.Option(
        ..., "--unit", help="Academic unit or department code (e.g., STAT)"
    ),
    output_file: Optional[str] = typer.Option(
        None, "--output", "-o", help="Output CSV file path. Defaults to stdout."
    ),
    config_file: Optional[str] = typer.Option(
        "cardgate.yaml",
        "--config",
        "-c",
        help="Path to config YAML",
    ),
):
    """
    Generate card key access spreadsheets for long-term employees (faculty, staff, postdocs) in an academic unit.
    """
    logger.info(f"Starting pipeline for employees...")
    people = fetch_employees(academic_unit)
    export_to_csv(people, academic_unit, config_file, output_path=output_file)


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
    config_file: Optional[str] = typer.Option(
        "cardgate.yaml",
        "--config",
        "-c",
        help="Path to config YAML",
    ),
):
    """
    Generate card key access spreadsheets for program-enrolled students (PhD, MA, BA).
    """
    logger.info(f"Starting pipeline for program students...")
    people = fetch_program_students(program_codes)
    export_to_csv(people, academic_unit, config_file, output_path=output_file)


if __name__ == "__main__":
    app()
