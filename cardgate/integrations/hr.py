import subprocess
import json
import logging
import os
from typing import List, Optional
from cardgate.models import Person

logger = logging.getLogger(__name__)


def get_employees(academic_unit: str) -> List[Person]:
    """
    Query HR for long-term employees in an academic unit.
    """
    logger.debug(f"Fetching employees for {academic_unit}")
    logger.warning("HR employee query not yet implemented - returning empty list.")
    return []
