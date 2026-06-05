import asyncio
import logging
import os
from typing import List
from cardgate.models import Person

logger = logging.getLogger(__name__)


async def _get_employees_async(hr_department: str) -> List[Person]:
    employees_id = os.getenv("UCBHR_EMPLOYEES_ID")
    employees_key = os.getenv("UCBHR_EMPLOYEES_KEY")
    departments_id = os.getenv("UCBHR_DEPARTMENTS_ID")
    departments_key = os.getenv("UCBHR_DEPARTMENTS_KEY")

    if not all([employees_id, employees_key, departments_id, departments_key]):
        raise ValueError(
            "Missing HR API credentials. Set UCBHR_EMPLOYEES_ID, UCBHR_EMPLOYEES_KEY, "
            "UCBHR_DEPARTMENTS_ID, and UCBHR_DEPARTMENTS_KEY environment variables."
        )

    from ucbhr import departments, info

    raw_employees = await departments.get_employees(
        departments_id, departments_key, hr_department
    )
    campus_uids = departments.extract_identifiers(raw_employees, "campus-uid")

    if not campus_uids:
        logger.info(f"No employees found for department: {hr_department}")
        return []

    logger.info(
        f"Found {len(campus_uids)} employees in {hr_department}. Fetching info..."
    )

    async def fetch_info(uid: str):
        try:
            data = await info.get(employees_id, employees_key, uid, "campus-uid")
            return uid, data
        except Exception as e:
            logger.warning(f"Failed to fetch info for {uid} (HTTP {getattr(e, 'status', '?')}): {e}")
            return uid, None

    tasks = [fetch_info(uid) for uid in campus_uids]
    results = await asyncio.gather(*tasks)

    people = []
    for uid, data in results:
        if not data:
            continue
        person = _build_person(uid, data)
        if person:
            people.append(person)

    logger.info(f"Successfully built {len(people)} Person records from {hr_department}")
    return people


def _build_person(uid: str, data: dict) -> Person:
    names = data.get("names", [])
    if not names:
        return None

    pref_name = None
    lived_name = None
    for n in names:
        code = n.get("type", {}).get("code")
        if code == "PRF":
            pref_name = n
        elif code == "PRI":
            lived_name = n

    best_name = pref_name or lived_name or names[0]
    first_name = best_name.get("givenName", "")
    last_name = best_name.get("familyName", "")
    middle_name = best_name.get("middleName", "")
    middle_initial = middle_name[0].upper() if middle_name else ""

    emails = data.get("emails", [])
    email = None
    for e in emails:
        if e.get("type", {}).get("code") == "BUSN":
            email = e.get("emailAddress")
            break
    if not email and emails:
        email = emails[0].get("emailAddress")

    if not first_name or not last_name:
        return None

    return Person(
        id=uid,
        uid=uid,
        first_name=first_name,
        last_name=last_name,
        middle_initial=middle_initial,
        email=email,
        role="Employees",
    )


def get_employees(hr_department: str) -> List[Person]:
    """
    Query HR for employees in an HR department code.
    """
    logger.debug(f"Fetching employees for HR department: {hr_department}")
    return asyncio.run(_get_employees_async(hr_department))
