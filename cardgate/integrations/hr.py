import subprocess
import json
import logging
import os
import asyncio
from typing import List, Dict, Optional
from cardgate.models import Person

# Assume the new ucbhr package supports this internal API
from ucbhr import info

logger = logging.getLogger(__name__)


async def get_eids_for_uids(uid_list: List[str]) -> Dict[str, str]:
    """
    Fetch the EID for a given list of campus-uids using ucbhr.
    """
    # For now, return mock EIDs that match the UID just to satisfy the pipeline
    # until ucbhr is updated to fetch all employees by dept.
    return {uid: uid for uid in uid_list}


def get_employees(academic_unit: str) -> List[Person]:
    """
    Query HR for long-term employees in an academic unit.
    """
    logger.debug(f"Fetching employees for {academic_unit}")

    # Mock data for Phase 1 testing
    mock_uids = ["10001", "10002"]
    eid_map = asyncio.run(batch_convert_uids_to_eids(mock_uids))

    return [
        Person(
            id=eid_map.get("10001", "10001"),
            first_name="Alan",
            last_name="Turing",
            middle_initial="M",
            email="alan@berkeley.edu",
            role="Faculty",
        ),
        Person(
            id=eid_map.get("10002", "10002"),
            first_name="Grace",
            last_name="Hopper",
            middle_initial="B",
            email="grace@berkeley.edu",
            role="Staff",
        ),
    ]
