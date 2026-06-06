import os
import logging
from flask_oidc import FlaskOIDC
from joserfc.registry import JWS_HEADER_REGISTRY, HeaderParameter

logger = logging.getLogger(__name__)

# CalNet includes a non-standard "client_id" claim in the JWT header of its
# ID tokens. Register it as an accepted JWS header parameter so joserfc
# does not reject it during ID token validation.
JWS_HEADER_REGISTRY.setdefault("client_id", HeaderParameter("Client ID", "str"))

CALNET_SERVERS = {
    "test": "https://auth-test.berkeley.edu",
    "prod": "https://auth.berkeley.edu",
}

DEFAULT_SCOPES = [
    "openid",
    "profile",
    "berkeley_edu_default",
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


def get_user_groups(oidc):
    """
    Returns the list of group strings from the current OIDC session, or None.
    Group strings are LDAP DNs like
    'cn=edu:berkeley:app:cardgate:users,ou=campus groups,dc=berkeley,dc=edu'.
    """
    if oidc is None:
        return None
    user = oidc.get_user()
    if user and "groups" in user:
        groups = user["groups"]
        if isinstance(groups, str):
            return [g.strip() for g in groups.split(",")]
        if isinstance(groups, list):
            return groups
    return None


def user_has_allowed_group(oidc, allowed_groups):
    """
    Checks whether the currently authenticated user belongs to at least one
    of the allowed groups.

    Args:
        oidc: The FlaskOIDC instance (or None if auth is disabled).
        allowed_groups: List of full group DN strings from the groups claim.

    Returns:
        True if the user is in an allowed group, OIDC is not configured, or
        allowed_groups is empty.
    """
    if oidc is None or not allowed_groups:
        return True

    groups = get_user_groups(oidc)
    if not groups:
        return False

    allowed = set(allowed_groups)
    for g in groups:
        if g in allowed:
            return True
    return False
