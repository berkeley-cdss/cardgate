import asyncio
import json
import os
import jmespath
import logging
import datetime
from typing import List, Optional, Dict, Tuple
from cardgate.models import Person

logger = logging.getLogger(__name__)

# Import from the sis python package
from sis import terms, classes, enrollments, sis as sis_core
from sis.student import (
    get_students_by_plan_code,
    get_students_by_id_list,
    deduplicate_students,
    extract_campus_uid,
    extract_student_id,
    extract_email,
)


def _extract_person_name(student: dict) -> Tuple[str, str, str]:
    """Extract (first_name, last_name, middle_initial) from a student's
    structured name records (preferring 'PRF' preferred name, falling back
    to 'PRI' lived name), reading fields directly rather than parsing a
    formatted 'Last, First' string. Mirrors hr._build_person's approach.
    """
    names = student.get("names", [])
    pref_name = None
    lived_name = None
    for n in names:
        code = n.get("type", {}).get("code")
        if code == "PRF":
            pref_name = n
        elif code == "PRI":
            lived_name = n

    best_name = pref_name or lived_name or (names[0] if names else None)
    if not best_name:
        return "", "", ""

    first_name = best_name.get("givenName", "")
    last_name = best_name.get("familyName", "")
    middle_name = best_name.get("middleName", "")
    middle_initial = middle_name[0].upper() if middle_name else ""
    return first_name, last_name, middle_initial


def _build_student_person(student: dict, role: str) -> Optional[Person]:
    """Build a Person from a raw SIS student record.

    Returns None if the record lacks a campus UID or a resolvable name.
    """
    uid = extract_campus_uid(student)
    if not uid:
        return None

    first_name, last_name, middle_initial = _extract_person_name(student)
    if not first_name or not last_name:
        logger.warning(f"Skipping SIS student {uid}: no resolvable name.")
        return None

    return Person(
        id=extract_student_id(student) or "",
        uid=uid,
        first_name=first_name,
        last_name=last_name,
        middle_initial=middle_initial,
        email=extract_email(student),
        role=role,
    )


async def get_term_dates(term_id: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Fetch beginDate and endDate for a given term_id.
    Returns (begin_date, end_date) as ISO date strings.
    """
    terms_id = os.getenv("SIS_TERMS_ID")
    terms_key = os.getenv("SIS_TERMS_KEY")

    if not terms_id or not terms_key:
        logger.warning(
            "SIS_TERMS_ID or SIS_TERMS_KEY not set. Cannot fetch term dates."
        )
        return None, None

    try:
        uri = f"{terms.terms_uri}/{term_id}"
        headers = {
            "Accept": "application/json",
            "app_id": terms_id,
            "app_key": terms_key,
        }
        data = await sis_core.get_items(uri, {}, headers, "terms")
        if data and len(data) > 0:
            return data[0].get("beginDate"), data[0].get("endDate")
    except Exception as e:
        logger.error(f"Failed to fetch term dates for {term_id}: {e}")

    return None, None


async def _get_program_students_async(
    program_codes: List[str],
    code_to_role: Optional[Dict[str, str]] = None,
) -> List[Person]:
    """
    Async implementation: query SIS for students in specific academic programs.
    """
    students_id = os.getenv("SIS_STUDENTS_ID")
    students_key = os.getenv("SIS_STUDENTS_KEY")
    if not students_id or not students_key:
        raise ValueError("SIS_STUDENTS_ID or SIS_STUDENTS_KEY not set.")

    all_students = []
    for code in program_codes:
        results = await get_students_by_plan_code(
            students_id, students_key, code, inc_acad=True
        )
        for student in results:
            all_students.append((student, code))

    # Deduplicate raw students first, keeping the first plan code seen
    seen_uids = {}
    deduped = []
    for student, plan_code in all_students:
        uid = extract_campus_uid(student)
        if uid and uid not in seen_uids:
            seen_uids[uid] = plan_code
            deduped.append(student)

    # Build Person objects
    people = []
    for student in deduped:
        uid = extract_campus_uid(student)

        # Determine role from the plan code that was matched
        plan_code = seen_uids.get(uid, "")
        role = "Program-enrolled"
        if code_to_role and plan_code in code_to_role:
            role = code_to_role[plan_code]

        person = _build_student_person(student, role)
        if person:
            people.append(person)

    return people


def get_program_students(
    program_codes: List[str],
    code_to_role: Optional[Dict[str, str]] = None,
) -> List[Person]:
    """
    Query SIS for students in specific academic programs.

    Args:
        program_codes: List of SIS academic plan codes (e.g. ["00891PHDG", "00891MAG"])
        code_to_role: Optional mapping of plan code to role string.
                      If provided, each Person's role is set from this mapping.
                      If not provided, role defaults to "Program-enrolled".
    """
    logger.debug(f"Fetching program students for codes {program_codes}")
    return asyncio.run(_get_program_students_async(program_codes, code_to_role))


async def _get_students_by_uids_async(uids: List[str]) -> List[Person]:
    students_id = os.getenv("SIS_STUDENTS_ID")
    students_key = os.getenv("SIS_STUDENTS_KEY")
    if not students_id or not students_key:
        raise ValueError("SIS_STUDENTS_ID or SIS_STUDENTS_KEY not set.")

    raw_students = await get_students_by_id_list(
        students_id, students_key, ",".join(uids), id_type="campus-uid"
    )

    people = []
    for student in raw_students:
        person = _build_student_person(student, role="UID List")
        if person:
            people.append(person)

    return people


def get_students_by_uids(uids: List[str]) -> List[Person]:
    """
    Query SIS for student records matching a list of CalNet UIDs.
    """
    if not uids:
        return []
    logger.debug(f"Fetching SIS info for {len(uids)} UID(s)")
    return asyncio.run(_get_students_by_uids_async(uids))


async def _get_course_enrolled_students_async(
    academic_unit: str,
    building: Optional[str],
    year: Optional[int],
    semester: Optional[str],
    from_time: Optional[str] = None,
) -> List[Person]:
    terms_id = os.getenv("SIS_TERMS_ID")
    terms_key = os.getenv("SIS_TERMS_KEY")
    classes_id = os.getenv("SIS_CLASSES_ID")
    classes_key = os.getenv("SIS_CLASSES_KEY")
    enrollments_id = os.getenv("SIS_ENROLLMENTS_ID")
    enrollments_key = os.getenv("SIS_ENROLLMENTS_KEY")

    if not all([terms_id, classes_id, enrollments_id]):
        raise ValueError(
            "Missing specific SIS API keys in the environment. Require SIS_TERMS_ID, SIS_CLASSES_ID, and SIS_ENROLLMENTS_ID."
        )

    # 1. Resolve Term ID
    if year and semester:
        term_id = await terms.get_term_id_from_year_sem(
            terms_id, terms_key, year, semester.lower()
        )
    else:
        term_id = await terms.get_term_id(terms_id, terms_key, "Current")

    logger.debug(f"Resolved term ID: {term_id}")

    # 2. Get all classes for the subject
    try:
        raw_classes = await classes.get_classes_by_subject_area(
            classes_id, classes_key, term_id, academic_unit, return_raw=True
        )
    except Exception as e:
        logger.error(f"Error fetching classes for {academic_unit}: {e}")
        return []

    # Extract unique catalog numbers
    catalog_numbers = list(
        set(jmespath.search("[].course.catalogNumber.formatted", raw_classes) or [])
    )

    logger.debug(
        f"Found {len(catalog_numbers)} catalog numbers for {academic_unit}. Fetching sections concurrently..."
    )

    target_time = None
    if from_time:
        try:
            parts = from_time.split(":")
            if len(parts) == 2:
                from_time = f"{from_time}:00"
            target_time = datetime.time.fromisoformat(from_time)
        except Exception as e:
            logger.error(
                f"Invalid time format for from_time: {from_time}. Use HH:MM or HH:MM:SS."
            )
            target_time = None

    # 3. Process sections concurrently
    section_tasks = [
        classes.get_sections(classes_id, classes_key, term_id, academic_unit, cn)
        for cn in catalog_numbers
    ]
    sections_results = await asyncio.gather(*section_tasks, return_exceptions=True)

    matching_section_ids = []
    enrolled_students = []
    seen_uids = set()

    for cn, sections in zip(catalog_numbers, sections_results):
        if isinstance(sections, Exception):
            logger.debug(
                f"Error fetching sections for {academic_unit} {cn}: {sections}"
            )
            continue

        for section in sections:
            if building is None and target_time is None:
                # No building or time filter: include every section
                meets_criteria = True
            else:
                meets_criteria = False
                for meeting in section.get("meetings", []):
                    if building is not None:
                        location_desc = meeting.get("location", {}).get(
                            "description", ""
                        )
                        # Check building match
                        if building.lower() not in location_desc.lower():
                            continue
                    if target_time:
                        start_time_str = meeting.get("startTime")
                        if not start_time_str:
                            continue
                        try:
                            meeting_time = datetime.time.fromisoformat(start_time_str)
                        except ValueError:
                            continue
                        if meeting_time >= target_time:
                            meets_criteria = True
                            break
                    else:
                        meets_criteria = True
                        break

            if meets_criteria:
                matching_section_ids.append(enrollments.section_id(section))

                # Extract course staff (instructors and GSIs) from this section
                try:
                    staff_objs = classes.section_instructor_objects(
                        section, role_filter="staff"
                    )
                    for staff_obj in staff_objs:
                        uid = jmespath.search(
                            "instructor.identifiers[?type=='campus-uid'].id | [0]",
                            staff_obj,
                        )
                        if not uid or uid in seen_uids:
                            continue
                        seen_uids.add(uid)

                        names = staff_obj.get("instructor", {}).get("names", [])
                        first_name, last_name, middle_initial = "Unknown", "", ""

                        pref_name = None
                        for n in names:
                            if n.get("type", {}).get("code") == "PRF":
                                pref_name = n
                                break
                            if not pref_name:
                                pref_name = n

                        if (
                            pref_name
                            and pref_name.get("givenName")
                            and pref_name.get("familyName")
                        ):
                            first_name = pref_name.get("givenName")
                            last_name = pref_name.get("familyName")
                            if pref_name.get("middleName"):
                                middle_initial = pref_name.get("middleName")[0].upper()
                            elif " " in first_name:
                                parts = first_name.split(" ", 1)
                                first_name = parts[0]
                                middle_initial = parts[1][0].upper()
                        else:
                            raw_name = (
                                pref_name.get("formattedName", "Unknown")
                                if pref_name
                                else "Unknown"
                            )
                            if "," in raw_name:
                                parts = raw_name.split(",", 1)
                                last_name = parts[0].strip()
                                first_part = parts[1].strip()
                                if " " in first_part:
                                    fn_parts = first_part.split(" ", 1)
                                    first_name = fn_parts[0]
                                    middle_initial = fn_parts[1][0].upper()
                                else:
                                    first_name = first_part
                            elif " " in raw_name:
                                parts = raw_name.split(" ", 1)
                                first_name = parts[0].strip()
                                last_name = parts[1].strip()

                        enrolled_students.append(
                            Person(
                                id=uid,  # Will batch convert these to SIDs at the end
                                uid=uid,
                                first_name=first_name,
                                last_name=last_name,
                                middle_initial=middle_initial,
                                email=None,  # SIS classes endpoint usually omits emails for staff
                                role="Course-staff",
                            )
                        )
                except Exception as e:
                    logger.debug(
                        f"Could not extract staff for section {enrollments.section_id(section)}: {e}"
                    )

    bldg_txt = f"meeting in {building}" if building else "(no building filter)"
    logger.debug(
        f"Found {len(matching_section_ids)} sections {bldg_txt}. Fetching enrollments concurrently..."
    )

    # 4. Get enrollments concurrently
    enrollment_tasks = [
        enrollments.get_section_enrollments(
            enrollments_id, enrollments_key, term_id, sect_id
        )
        for sect_id in matching_section_ids
    ]
    enrollments_results = await asyncio.gather(
        *enrollment_tasks, return_exceptions=True
    )

    for sect_id, section_enrollments in zip(matching_section_ids, enrollments_results):
        if isinstance(section_enrollments, Exception):
            logger.debug(
                f"Error fetching enrollments for section {sect_id}: {section_enrollments}"
            )
            continue

        for enr in section_enrollments:
            sid_search = jmespath.search(
                "student.identifiers[?type=='student-id'].id | [0]", enr
            )
            uid_search = enrollments.enrollment_campus_uid(enr)
            sid = sid_search or ""

            if not sid or sid in seen_uids:
                continue
            seen_uids.add(sid)

            # Names often come in as "Last, First" or "First Last"
            raw_name = enrollments.enrollment_name(enr) or "Unknown"
            email = enrollments.enrollment_campus_email(enr)

            first_name, last_name, middle_initial = "", "", ""

            # Try to get structured name
            names_list = enr.get("student", {}).get("names", [])
            pref_name = None
            lived_name = None
            for n in names_list:
                code = n.get("type", {}).get("code")
                if code == "PRF":
                    pref_name = n
                elif code == "PRI":
                    lived_name = n

            best_name = pref_name or lived_name
            if best_name and best_name.get("givenName") and best_name.get("familyName"):
                first_name = best_name.get("givenName")
                last_name = best_name.get("familyName")
                if best_name.get("middleName"):
                    middle_initial = best_name.get("middleName")[0].upper()
                elif " " in first_name:
                    # Some systems put "First Middle" in givenName
                    parts = first_name.split(" ", 1)
                    first_name = parts[0]
                    middle_initial = parts[1][0].upper()
            else:
                # Fallback to string splitting
                if "," in raw_name:
                    parts = raw_name.split(",", 1)
                    last_name = parts[0].strip()
                    first_part = parts[1].strip()
                    if " " in first_part:
                        fn_parts = first_part.split(" ", 1)
                        first_name = fn_parts[0]
                        middle_initial = fn_parts[1][0].upper()
                    else:
                        first_name = first_part
                elif " " in raw_name:
                    parts = raw_name.split(" ", 1)
                    first_name = parts[0].strip()
                    last_name = parts[1].strip()

            enrolled_students.append(
                Person(
                    id=sid,
                    uid=uid_search,
                    first_name=first_name,
                    last_name=last_name,
                    middle_initial=middle_initial,
                    email=email,
                    role="Course-enrolled",
                )
            )

    return enrolled_students


def get_course_enrolled_students(
    academic_unit: str,
    building: Optional[str] = None,
    year: Optional[int] = None,
    semester: Optional[str] = None,
    from_time: Optional[str] = None,
) -> List[Person]:
    """
    Query SIS for courses taught by unit (optionally filtered by building),
    then get enrolled students and course staff.
    """
    return asyncio.run(
        _get_course_enrolled_students_async(
            academic_unit, building, year, semester, from_time
        )
    )
