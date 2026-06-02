import os
import logging
import requests
from requests.auth import HTTPBasicAuth
from typing import Optional

logger = logging.getLogger(__name__)

C1C_API_BASE = "https://test-c1c-api.sait-west.berkeley.edu/c1c-api/v1/CardData"


def get_seos_for_uid(uid: str) -> Optional[str]:
    """
    Fetch the 'seos' card data for a given campus UID from the Cal1Card API.
    """
    username = os.environ.get("C1C_APP_ID")
    password = os.environ.get("C1C_APP_KEY")

    if not username or not password:
        logger.warning(
            "C1C_APP_ID or C1C_APP_KEY environment variables not set. Cannot fetch card data."
        )
        return None

    try:
        # Based on curl -X 'GET' '.../CardData/854589?id-type=campus-uid' -H 'accept: application/json' -H 'Authorization: Basic ...'
        url = f"{C1C_API_BASE}/{uid}"
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
            data = response.json()
            return data.get("seos")
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
