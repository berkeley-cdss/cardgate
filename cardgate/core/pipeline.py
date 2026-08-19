import csv
import sys
import logging
from pathlib import Path
from typing import List, Dict, Optional

from .clearances import load_cardgate_config, get_clearance_locations
from cardgate.integrations import hr, sis, c1c
from cardgate.models import Person

logger = logging.getLogger(__name__)


def get_programs(config: dict) -> List[dict]:
    """Returns the list of academic program definitions from config."""
    return config.get("programs", [])


def fetch_employees(hr_departments: List[str]) -> List[Person]:
    seen: Dict[str, Person] = {}
    for dept in hr_departments:
        logger.info(f"Fetching HR employees for department: {dept}...")
        try:
            employees = hr.get_employees(dept)
        except Exception as e:
            logger.warning(f"Skipping department {dept}: {e}")
            continue
        for p in employees:
            p.department = dept
            key = p.uid or p.id
            if key not in seen:
                seen[key] = p
    people = list(seen.values())
    logger.info(f"Total unique employees identified: {len(people)}")
    return people


def fetch_program_students(
    program_codes: List[str],
    code_to_role: Optional[Dict[str, str]] = None,
) -> List[Person]:
    logger.info(f"Fetching SIS students for program codes: {program_codes}...")
    students = sis.get_program_students(program_codes, code_to_role=code_to_role)
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


def fetch_people_by_uids(uids: List[str]) -> List[Person]:
    """
    Resolve a list of CalNet UIDs to Person records.

    Tries SIS (students) first with a single batched lookup, then falls back
    to HR (employees) per-UID for any UIDs SIS didn't resolve. UIDs that
    match neither system are dropped and logged, not included as blank
    placeholder rows.
    """
    logger.info(f"Resolving {len(uids)} UID(s)...")

    resolved: Dict[str, Person] = {}
    try:
        for p in sis.get_students_by_uids(uids):
            if p.uid:
                resolved[p.uid] = p
    except Exception as e:
        logger.warning(f"SIS UID lookup failed: {e}")

    remaining = [u for u in uids if u not in resolved]
    if remaining:
        try:
            for p in hr.get_employees_by_uids(remaining):
                if p.uid:
                    resolved[p.uid] = p
        except Exception as e:
            logger.warning(f"HR UID lookup failed: {e}")

    people = [resolved[u] for u in uids if u in resolved]
    unresolved = [u for u in uids if u not in resolved]
    if unresolved:
        logger.warning(
            f"Could not resolve {len(unresolved)} of {len(uids)} UID(s) to a "
            f"person: {', '.join(unresolved)}"
        )

    logger.info(f"Resolved {len(people)} of {len(uids)} UID(s) to a person.")
    return people


def extract_uids_from_csv_rows(rows: List[List[str]]) -> List[str]:
    """
    Given CSV rows (as returned by csv.reader), extract candidate UID
    strings.

    If the first row has a 'uid' column (case-insensitive), only that
    column's values are read from the remaining rows. Otherwise, every
    row's first column is treated as a UID (one per line). Values are
    stripped but not deduplicated or filtered for emptiness.
    """
    if not rows:
        return []

    header = [cell.strip().lower() for cell in rows[0]]
    if "uid" in header:
        uid_col = header.index("uid")
        return [row[uid_col].strip() for row in rows[1:] if uid_col < len(row)]
    else:
        return [row[0].strip() for row in rows if row]


import concurrent.futures


def fetch_card_data(people: List[Person], progress_callback=None) -> None:
    """
    Populate the seos_number and lowprox_number fields for each person using the C1C API.
    Uses a thread pool to fetch data concurrently.
    progress_callback(done, total) is called after each person completes.
    """
    if not people:
        return

    # Validate C1C API is configured before spawning workers
    import os

    if not os.environ.get("C1C_API_BASE_URL"):
        raise ValueError(
            "C1C_API_BASE_URL environment variable not set. "
            "Cannot fetch card key data."
        )

    logger.info(f"Fetching card key data for {len(people)} people...")

    def process_person(person: Person):
        target_uid = person.uid if person.uid else person.id
        data = c1c.get_card_data(target_uid)
        if data:
            if data.get("seos"):
                person.seos_number = data["seos"]
            if data.get("lowprox"):
                person.lowprox_number = data["lowprox"]

    total = len(people)
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(process_person, p) for p in people]
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            if progress_callback:
                progress_callback(i + 1, total)
            future.result()  # surface exceptions

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
        "Student/Employee ID Number",
        "6 digit (Low Frequency)",
        "7 digit (High Frequency)",
        "Type of Card",
        "Action",
    ]
    for _ in range(10):
        headers.append("Clearance Name")

    is_file_like = hasattr(output_path, "write")

    # People with any card data first, those with none at bottom
    people.sort(key=lambda p: 0 if (p.lowprox_number or p.seos_number) else 1)

    def _write_rows(writer):
        writer.writerow(headers)

        for person in people:
            row = [
                "",  # Date Submitted
                person.last_name,
                person.first_name,
                person.middle_initial,
                person.department or academic_unit,
                person.id,
                person.lowprox_number or "",  # 6 digit (Low Frequency)
                person.seos_number or "",  # 7 digit (High Frequency / seos)
                "CalID",  # Type of Card
                "Add Clearance",  # Action
            ]
            for i in range(10):
                if i < len(clearance_names):
                    row.append(clearance_names[i])
                else:
                    row.append("")

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
