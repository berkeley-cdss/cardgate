import csv
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional

from .clearances import load_cardgate_config, get_clearance_locations, get_date_buffer
from cardgate.integrations import hr, sis
from cardgate.models import Person

logger = logging.getLogger(__name__)


def fetch_employees(academic_unit: str) -> List[Person]:
    logger.info(f"Fetching HR employees for unit: {academic_unit}...")
    employees = hr.get_employees(academic_unit)
    logger.info(f"Total employees identified: {len(employees)}")
    return employees


def fetch_program_students(program_codes: List[str]) -> List[Person]:
    logger.info(f"Fetching SIS students for program codes: {program_codes}...")
    students = sis.get_program_students(program_codes)
    logger.info(f"Total program students identified: {len(students)}")
    return students


def fetch_course_people(
    academic_unit: str,
    building: str,
    year: Optional[int] = None,
    semester: Optional[str] = None,
    from_time: Optional[str] = None,
) -> List[Person]:
    term_str = f"{semester} {year}" if (year and semester) else "current term"
    logger.info(
        f"Fetching course enrollments and staff for {academic_unit} in {building} for {term_str}..."
    )

    # We still want to deduplicate within the course people fetch (e.g. someone is staff and enrolled)
    all_people: Dict[str, Person] = {}

    course_people = sis.get_course_enrolled_students(
        academic_unit, building, year, semester, from_time
    )
    for p in course_people:
        if p.id not in all_people:
            all_people[p.id] = p
        else:
            # If they are already in as Course-staff, don't overwrite with Course-enrolled
            if p.role == "Course-staff":
                all_people[p.id] = p

    final_people = list(all_people.values())
    logger.info(
        f"Total unique course-related individuals identified: {len(final_people)}"
    )
    return final_people


def export_to_csv(
    people: List[Person],
    academic_unit: str,
    config_path: str,
    output_path: Optional[str] = None,
    term_begin: Optional[str] = None,
    term_end: Optional[str] = None,
):
    """
    Exports the standardized Person data to an intermediate CSV.
    If output_path is None, prints to sys.stdout.
    Uses term dates and clearance config to populate date fields.
    """
    if not people:
        logger.warning("No people to export. Skipping CSV generation.")
        return

    try:
        config = load_cardgate_config(config_path)
    except FileNotFoundError:
        logger.warning(f"Config file not found: {config_path}")
        config = {"clearances": [], "buffer": {"activation_days": 0, "expiration_days": 0}}

    clearance_names = get_clearance_locations(config)
    act_buffer, exp_buffer = get_date_buffer(config)

    act_date = ""
    exp_date = ""

    if term_begin:
        try:
            begin_dt = datetime.strptime(term_begin, "%Y-%m-%d")
            act_dt = begin_dt + timedelta(days=act_buffer)
            act_date = act_dt.strftime("%Y-%m-%d")
        except ValueError:
            logger.warning(f"Invalid term_begin date: {term_begin}")

    if term_end:
        try:
            end_dt = datetime.strptime(term_end, "%Y-%m-%d")
            exp_dt = end_dt + timedelta(days=exp_buffer)
            exp_date = exp_dt.strftime("%Y-%m-%d")
        except ValueError:
            logger.warning(f"Invalid term_end date: {term_end}")

    num_clearances = len(clearance_names)
    if num_clearances == 0:
        num_clearances = 1

    headers = [
        "Date Submitted",
        "Last Name",
        "First Name",
        "MI",
        "Department",
        "SID/EID Number",
        "Prox Number",
        "Type of Card",
        "Action",
    ]

    for i in range(num_clearances):
        headers.extend(["Clearance Name", "Activation Date", "Expiration Date"])

    def _write_rows(writer):
        writer.writerow(headers)
        for person in people:
            row = [
                "",  # Date Submitted
                person.last_name,
                person.first_name,
                person.middle_initial,
                academic_unit,
                person.id,
                "",  # Prox Number
                "CalID",  # Type of Card
                "Add Clearance",  # Action
            ]

            for clearance in clearance_names:
                row.extend([clearance, act_date, exp_date])

            writer.writerow(row)

    if output_path:
        path = Path(output_path)
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            _write_rows(writer)
        logger.info(f"Data exported successfully to {output_path}")
    else:
        writer = csv.writer(sys.stdout)
        _write_rows(writer)
