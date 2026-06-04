import os
import logging
import requests
from requests.auth import HTTPBasicAuth
from typing import Optional

logger = logging.getLogger(__name__)


def _api_base() -> str:
    """Return the C1C API base URL from env, falling back to test."""
    return os.environ.get(
        "C1C_API_BASE_URL",
        "https://test-c1c-api.sait-west.berkeley.edu",
    ) + "/c1c-api/v1/CardData"


def get_card_data(uid: str) -> Optional[dict]:
    """
    Fetch card data for a given campus UID from the Cal1Card API.
    Returns the full response dict, or None if not found / on error.
    """
    username = os.environ.get("C1C_APP_ID")
    password = os.environ.get("C1C_APP_KEY")

    if not username or not password:
        logger.warning(
            "C1C_APP_ID or C1C_APP_KEY environment variables not set. Cannot fetch card data."
        )
        return None

    try:
        url = f"{_api_base()}/{uid}"
        params = {"id-type": "campus-uid"}
        headers = {"accept": "application/json"}

        response = requests.get(
            url,
            params=params,
            headers=headers,
            auth=HTTPBasicAuth(username, password),
            timeout=10,
        )

        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            logger.debug(f"No card data found for UID {uid}")
            return None
        else:
            logger.warning(
                f"Unexpected response from C1Card API for UID {uid}: {response.status_code} - {response.text}"
            )
            return None

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching card data for UID {uid}: {e}")
        return None
