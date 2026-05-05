import csv
import sys
import logging
from pathlib import Path
from typing import List, Dict, Optional

from .config import load_config
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

def fetch_course_people(academic_unit: str, building: str, year: Optional[int] = None, semester: Optional[str] = None) -> List[Person]:
    term_str = f"{semester} {year}" if (year and semester) else "current term"
    logger.info(f"Fetching course enrollments and staff for {academic_unit} in {building} for {term_str}...")
    
    # We still want to deduplicate within the course people fetch (e.g. someone is staff and enrolled)
    all_people: Dict[str, Person] = {}
    
    course_people = sis.get_course_enrolled_students(academic_unit, building, year, semester)
    for p in course_people:
        if p.id not in all_people:
            all_people[p.id] = p
        else:
            # If they are already in as Course-staff, don't overwrite with Course-enrolled
            if p.role == "Course-staff":
                all_people[p.id] = p
                
    final_people = list(all_people.values())
    logger.info(f"Total unique course-related individuals identified: {len(final_people)}")
    return final_people

def export_to_csv(people: List[Person], academic_unit: str, output_path: Optional[str] = None):
    """
    Exports the standardized Person data to an intermediate CSV.
    If output_path is None, prints to sys.stdout.
    """
    if not people:
        logger.warning("No people to export. Skipping CSV generation.")
        return

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
        "Clearance Name",
        "Activation Date",
        "Expiration Date",
    ]

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
                "",  # Type of Card
                "Add",  # Action
                person.role,  # Clearance Name (mapped to role for now)
                "",  # Activation Date
                "",  # Expiration Date
            ]
            # Pad the remaining 9 clearance columns (3 sets of 3) with empty strings
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
