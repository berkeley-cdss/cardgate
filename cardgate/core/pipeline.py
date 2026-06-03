import csv
import sys
import logging
from pathlib import Path
from typing import List, Dict, Optional

from .clearances import load_cardgate_config, get_clearance_locations
from cardgate.integrations import hr, sis, c1c
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


import concurrent.futures


def fetch_card_data(people: List[Person]) -> None:
    """
    Populate the seos_number and lowprox_number fields for each person using the C1C API.
    Uses a thread pool to fetch data concurrently.
    """
    logger.info(f"Fetching card key data for {len(people)} people...")

    def process_person(person: Person):
        target_uid = person.uid if person.uid else person.id
        data = c1c.get_card_data(target_uid)
        if data:
            if data.get("seos"):
                person.seos_number = data["seos"]
            if data.get("lowprox"):
                person.lowprox_number = data["lowprox"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        executor.map(process_person, people)

    logger.info("Finished fetching card key data.")


def export_to_csv(
    people: List[Person],
    academic_unit: str,
    config_path: str,
    output_path: Optional[str] = None,
    clearances: Optional[List[str]] = None,
):
    """
    Exports the standardized Person data to a CSV matching the Facilities
    Services Electronic Access Card Key Request template format.

    If clearances is provided, it overrides the clearance names from the config.
    """
    if not people:
        logger.warning("No people to export. Skipping CSV generation.")
        return ""

    if clearances is not None:
        clearance_names = clearances
    else:
        try:
            config = load_cardgate_config(config_path)
        except (FileNotFoundError, TypeError):
            logger.warning(f"Config file not found or invalid: {config_path}")
            config = {"clearances": []}
        clearance_names = get_clearance_locations(config)

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

    is_file_like = hasattr(output_path, "write")

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
                person.card_key_number or "",  # Prox Number (seos)
                "CalID",  # Type of Card
                "Add Clearance",  # Action
            ]

            for clearance in clearance_names:
                row.extend([clearance, act_date, exp_date])

            writer.writerow(row)

    if output_path:
        if is_file_like:
            writer = csv.writer(output_path)
            _write_rows(writer)
            return ""
        else:
            path = Path(output_path)
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                _write_rows(writer)
            logger.info(f"Data exported successfully to {output_path}")
            return ""
    else:
        writer = csv.writer(sys.stdout)
        _write_rows(writer)
        return ""
