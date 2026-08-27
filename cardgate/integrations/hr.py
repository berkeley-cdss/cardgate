import asyncio
import logging
import os
from typing import List, Optional, Set

from cardgate.models import Person

logger = logging.getLogger(__name__)


async def _fetch_department_uids(
    departments_id: str,
    departments_key: str,
    dept_code: str,
    include_future: bool = True,
    page_size: int = 500,
) -> List[str]:
    """Fetch campus UIDs for an HR department, paging through results.

    The v4 /departments/{id}/employees endpoint caps page size and reports
    remaining counts in a top-level 'offset' object; ucbhr's helper does not
    paginate, so we do it here.
    """
    import aiohttp
    from ucbhr import hr as ucbhr_core

    url = f"{ucbhr_core.departments_url}/{dept_code}/employees"
    headers = {
        "Accept": "application/json",
        "app_id": departments_id,
        "app_key": departments_key,
    }
    params = {
        "page-size": page_size,
        "employee-hr-status": "A",
    }
    if include_future:
        # Future-dated appointments (e.g. Fall ASEs entered early) are
        # excluded by default by the API; we want them for provisioning.
        params["include-future-employees"] = "true"

    uids: List[str] = []
    seen: Set[str] = set()
    page = 1

    async with aiohttp.ClientSession() as session:
        while True:
            request_params = dict(params)
            request_params["page-number"] = page
            async with session.get(url, headers=headers, params=request_params) as r:
                if r.status == 404:
                    break
                if r.status != 200:
                    body = await r.text()
                    raise RuntimeError(
                        f"HR departments API returned {r.status} for {dept_code}: {body[:200]}"
                    )
                data = await r.json()

            employees = data.get("response") or []
            new_count = 0
            for emp in employees:
                for ident in emp.get("identifiers", []):
                    if ident.get("type") == "campus-uid":
                        uid = ident.get("id")
                        if uid and uid not in seen:
                            seen.add(uid)
                            uids.append(uid)
                            new_count += 1
                        break

            offset = data.get("offset") or {}
            try:
                remaining = int(offset.get("remaining", 0) or 0)
            except (TypeError, ValueError):
                remaining = 0

            if remaining <= 0 or new_count == 0:
                break
            page += 1

    return uids


async def _filter_uids_by_job_codes(
    employees_id: str,
    employees_key: str,
    dept_code: str,
    uids: List[str],
    wanted_codes: Set[str],
    concurrency_limit: int = 10,
) -> List[str]:
    """Keep only UIDs holding an active job in dept_code whose title code is in wanted_codes.

    Title codes are compared zero-padded to six digits (UCPath format).
    Department matching guards against students holding concurrent ASE jobs
    in other departments.
    """
    import jmespath
    from ucbhr import jobs as ucbhr_jobs

    semaphore = asyncio.Semaphore(concurrency_limit)
    matched: Set[str] = set()

    async def check(uid: str):
        async with semaphore:
            try:
                job_list = await ucbhr_jobs.get(employees_id, employees_key, uid, "campus-uid")
            except Exception as e:
                logger.warning(f"Jobs lookup failed for UID {uid}: {e}")
                return
        for job in job_list or []:
            code = (jmespath.search("position.jobCode.code.code", job) or "").zfill(6)
            if code not in wanted_codes:
                continue
            status_code = jmespath.search("status.hrStatus.code", job)
            if status_code and status_code.upper() != "A":
                continue
            job_dept = jmespath.search("department.code", job) or ""
            if job_dept and job_dept.upper() != dept_code.upper():
                continue
            matched.add(uid)
            return

    await asyncio.gather(*(check(u) for u in uids))
    return [u for u in uids if u in matched]


async def _fetch_info_for_uids(employees_id: str, employees_key: str, uids: List[str]):
    """Concurrently fetch HR 'info' records for a list of campus UIDs.

    Returns a list of (uid, data) tuples; data is None for UIDs that failed.
    """
    from ucbhr import info

    async def fetch_info(uid: str):
        try:
            data = await info.get(employees_id, employees_key, uid, "campus-uid")
            return uid, data
        except Exception as e:
            logger.warning(f"Failed to fetch info for {uid} (HTTP {getattr(e, 'status', '?')}): {e}")
            return uid, None

    tasks = [fetch_info(uid) for uid in uids]
    return await asyncio.gather(*tasks)


async def _get_employees_async(
    hr_department: str, job_title_codes: Optional[Set[str]] = None
) -> List[Person]:
    employees_id = os.getenv("UCBHR_EMPLOYEES_ID")
    employees_key = os.getenv("UCBHR_EMPLOYEES_KEY")
    departments_id = os.getenv("UCBHR_DEPARTMENTS_ID")
    departments_key = os.getenv("UCBHR_DEPARTMENTS_KEY")

    if not all([employees_id, employees_key, departments_id, departments_key]):
        raise ValueError(
            "Missing HR API credentials. Set UCBHR_EMPLOYEES_ID, UCBHR_EMPLOYEES_KEY, "
            "UCBHR_DEPARTMENTS_ID, and UCBHR_DEPARTMENTS_KEY environment variables."
        )

    campus_uids = await _fetch_department_uids(
        departments_id, departments_key, hr_department
    )

    if not campus_uids:
        logger.info(f"No employees found for department: {hr_department}")
        return []

    logger.info(
        f"Found {len(campus_uids)} employees in {hr_department}. Fetching info..."
    )

    if job_title_codes:
        codes_str = ", ".join(sorted(job_title_codes))
        logger.info(
            f"Filtering {len(campus_uids)} employees by job title codes: {codes_str}"
        )
        campus_uids = await _filter_uids_by_job_codes(
            employees_id,
            employees_key,
            hr_department,
            campus_uids,
            job_title_codes,
        )
        logger.info(f"{len(campus_uids)} employee(s) matched the title code filter.")
        if not campus_uids:
            return []

    results = await _fetch_info_for_uids(employees_id, employees_key, campus_uids)

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

    # Use hr-employee-id as the person's primary ID; leave blank if unavailable
    eid = ""
    for ident in data.get("identifiers", []):
        if ident.get("type") == "hr-employee-id":
            eid = ident.get("id", "")
            break

    return Person(
        id=eid,
        uid=uid,
        first_name=first_name,
        last_name=last_name,
        middle_initial=middle_initial,
        email=email,
        role="Employees",
    )


def get_employees(
    hr_department: str, job_title_codes: Optional[List[str]] = None
) -> List[Person]:
    """
    Query HR for employees in an HR department code.

    If job_title_codes is provided (UCPath title codes), only people holding
    an active job with one of those codes in the department are returned.
    """
    logger.debug(f"Fetching employees for HR department: {hr_department}")
    wanted = {str(c).zfill(6) for c in job_title_codes} if job_title_codes else None
    return asyncio.run(_get_employees_async(hr_department, wanted))


async def _get_employees_by_uids_async(uids: List[str]) -> List[Person]:
    employees_id = os.getenv("UCBHR_EMPLOYEES_ID")
    employees_key = os.getenv("UCBHR_EMPLOYEES_KEY")

    if not employees_id or not employees_key:
        raise ValueError(
            "Missing HR API credentials. Set UCBHR_EMPLOYEES_ID and "
            "UCBHR_EMPLOYEES_KEY environment variables."
        )

    results = await _fetch_info_for_uids(employees_id, employees_key, uids)

    people = []
    for uid, data in results:
        if not data:
            continue
        person = _build_person(uid, data)
        if person:
            people.append(person)

    return people


def get_employees_by_uids(uids: List[str]) -> List[Person]:
    """
    Query HR directly for a list of CalNet UIDs, independent of department roster.
    """
    if not uids:
        return []
    logger.debug(f"Fetching HR info for {len(uids)} UID(s)")
    return asyncio.run(_get_employees_by_uids_async(uids))
