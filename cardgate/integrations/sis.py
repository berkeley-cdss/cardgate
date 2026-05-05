import asyncio
import json
import os
import jmespath
import logging
from typing import List, Optional, Dict
from cardgate.models import Person

logger = logging.getLogger(__name__)

# Import from the sis python package
from sis import terms, classes, enrollments, student

async def batch_convert_uids_to_sids(uids: List[str], concurrency_limit: int = 10) -> Dict[str, str]:
    """Safely fetch SIDs for multiple UIDs concurrently using sis.student."""
    students_id = os.getenv("SIS_STUDENTS_ID")
    students_key = os.getenv("SIS_STUDENTS_KEY")
    
    if not students_id or not students_key:
        logger.warning("SIS_STUDENTS_ID or SIS_STUDENTS_KEY not set. Returning UIDs as fallback.")
        return {uid: uid for uid in uids}

    semaphore = asyncio.Semaphore(concurrency_limit)
    
    async def fetch_with_semaphore(uid):
        async with semaphore:
            try:
                identifiers = await student.get_student(
                    app_id=students_id,
                    app_key=students_key,
                    identifier=uid,
                    id_type="campus-uid",
                    item_key="identifiers"
                )
                expr = "[?type=='student-id'].id | [0]"
                sid = jmespath.search(expr, identifiers)
                return uid, sid or uid # Fallback to UID if SID not found
            except Exception as e:
                logger.debug(f"Failed to fetch SID for UID {uid}: {e}")
                return uid, uid # Fallback to UID

    tasks = [fetch_with_semaphore(uid) for uid in uids]
    results = await asyncio.gather(*tasks)
    return dict(results)

def get_program_students(program_codes: List[str]) -> List[Person]:
    """
    Query SIS for students in specific academic programs.
    NOTE: Requires an update to `sis-cli` to query students by program code.
    """
    logger.debug(f"Fetching program students for codes {program_codes}")
    
    # Mock data for Phase 1 testing
    mock_uids = ["20001"]
    sid_map = asyncio.run(batch_convert_uids_to_sids(mock_uids))
    
    return [
        Person(id=sid_map.get("20001", "20001"), first_name="Ada", last_name="Lovelace", email="ada@berkeley.edu", role="MA"),
    ]

async def _get_course_enrolled_students_async(academic_unit: str, building: str, year: Optional[int], semester: Optional[str]) -> List[Person]:
    terms_id = os.getenv("SIS_TERMS_ID")
    terms_key = os.getenv("SIS_TERMS_KEY")
    classes_id = os.getenv("SIS_CLASSES_ID")
    classes_key = os.getenv("SIS_CLASSES_KEY")
    enrollments_id = os.getenv("SIS_ENROLLMENTS_ID")
    enrollments_key = os.getenv("SIS_ENROLLMENTS_KEY")
    
    if not all([terms_id, classes_id, enrollments_id]):
        raise ValueError("Missing specific SIS API keys in the environment. Require SIS_TERMS_ID, SIS_CLASSES_ID, and SIS_ENROLLMENTS_ID.")

    # 1. Resolve Term ID
    if year and semester:
        term_id = await terms.get_term_id_from_year_sem(terms_id, terms_key, year, semester.lower())
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
    catalog_numbers = list(set(
        jmespath.search("[].course.catalogNumber.formatted", raw_classes) or []
    ))
    
    logger.debug(f"Found {len(catalog_numbers)} catalog numbers for {academic_unit}. Fetching sections concurrently...")
    
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
            logger.debug(f"Error fetching sections for {academic_unit} {cn}: {sections}")
            continue
            
        for section in sections:
            meets_in_building = False
            meetings = section.get("meetings", [])
            for meeting in meetings:
                location_desc = meeting.get("location", {}).get("description", "")
                if building.lower() in location_desc.lower():
                    meets_in_building = True
                    break
            
            if meets_in_building:
                matching_section_ids.append(enrollments.section_id(section))

                # Extract course staff (instructors and GSIs) from this section
                try:
                    staff_objs = classes.section_instructor_objects(section, role_filter="staff")
                    for staff_obj in staff_objs:
                        uid = jmespath.search("instructor.identifiers[?type=='campus-uid'].id | [0]", staff_obj)
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
                                
                        if pref_name and pref_name.get("givenName") and pref_name.get("familyName"):
                            first_name = pref_name.get("givenName")
                            last_name = pref_name.get("familyName")
                            if pref_name.get("middleName"):
                                middle_initial = pref_name.get("middleName")[0].upper()
                            elif " " in first_name:
                                parts = first_name.split(" ", 1)
                                first_name = parts[0]
                                middle_initial = parts[1][0].upper()
                        else:
                            raw_name = pref_name.get("formattedName", "Unknown") if pref_name else "Unknown"
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

                        enrolled_students.append(Person(
                            id=uid,  # Will batch convert these to SIDs at the end
                            first_name=first_name,
                            last_name=last_name,
                            middle_initial=middle_initial,
                            email=None,  # SIS classes endpoint usually omits emails for staff
                            role="Course-staff"
                        ))
                except Exception as e:
                    logger.debug(f"Could not extract staff for section {enrollments.section_id(section)}: {e}")

    logger.debug(f"Found {len(matching_section_ids)} sections meeting in {building}. Fetching enrollments concurrently...")

    # 4. Get enrollments concurrently
    enrollment_tasks = [
        enrollments.get_section_enrollments(enrollments_id, enrollments_key, term_id, sect_id)
        for sect_id in matching_section_ids
    ]
    enrollments_results = await asyncio.gather(*enrollment_tasks, return_exceptions=True)

    for sect_id, section_enrollments in zip(matching_section_ids, enrollments_results):
        if isinstance(section_enrollments, Exception):
            logger.debug(f"Error fetching enrollments for section {sect_id}: {section_enrollments}")
            continue
            
        for enr in section_enrollments:
            sid_search = jmespath.search("student.identifiers[?type=='student-id'].id | [0]", enr)
            uid_search = enrollments.enrollment_campus_uid(enr)
            sid = sid_search or uid_search
            
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
            
            enrolled_students.append(Person(
                id=sid,
                first_name=first_name,
                last_name=last_name,
                middle_initial=middle_initial,
                email=email,
                role="Course-enrolled"
            ))

    # Convert all UIDs to SIDs in a final batch step
    uids_to_convert = [p.id for p in enrolled_students]
    if uids_to_convert:
        logger.debug(f"Converting {len(uids_to_convert)} UIDs to SIDs...")
        sid_map = await batch_convert_uids_to_sids(uids_to_convert)
        for p in enrolled_students:
            p.id = sid_map.get(p.id, p.id)

    return enrolled_students

def get_course_enrolled_students(academic_unit: str, building: str, year: Optional[int] = None, semester: Optional[str] = None) -> List[Person]:
    """
    Query SIS for courses taught by unit in specific building, then get enrolled students.
    """
    return asyncio.run(_get_course_enrolled_students_async(academic_unit, building, year, semester))
