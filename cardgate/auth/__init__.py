import os
import logging
from flask_oidc import FlaskOIDC

logger = logging.getLogger(__name__)

CALNET_SERVERS = {
    "test": "https://auth-test.berkeley.edu",
    "prod": "https://auth.berkeley.edu",
}

DEFAULT_SCOPES = [
    "openid",
    "profile",
    "email",
    "berkeley_edu_default",
    "berkeley_edu_groups",
    "berkeley_edu_dept_number",
    "berkeley_edu_ou",
]


def init_oidc(app):
    client_id = os.environ.get("CLIENT_ID")
    client_secret = os.environ.get("CLIENT_SECRET")

    if not client_id or not client_secret:
        logger.warning(
            "CLIENT_ID and CLIENT_SECRET not set; OIDC authentication disabled. "
            "The web app will run without authentication for local development."
        )
        app.config["OIDC_ENABLED"] = False
        return None

    calnet_env = os.environ.get("CALNET_ENVIRONMENT", "prod")
    oidc_server = CALNET_SERVERS.get(calnet_env, CALNET_SERVERS["prod"])

    oidc = FlaskOIDC(
        app,
        client_id=client_id,
        client_secret=client_secret,
        oidc_server=oidc_server,
        server_metadata_path="/cas/oidc/.well-known/openid-configuration",
        logout_redirect_url=f"{oidc_server}/cas/oidc/oidcLogout",
        scopes=DEFAULT_SCOPES,
    )
    app.config["OIDC_ENABLED"] = True
    return oidc


def login_required(oidc):
    """
    Decorator that requires OIDC authentication.
    If OIDC is not configured, allows access without authentication (dev mode).
    """
    if oidc is None:
        return lambda f: f

    return oidc.login_required
