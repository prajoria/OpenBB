"""Safe requests for caller-supplied Congress.gov and GovInfo URLs (#2242)."""

# Exact hosts for caller-supplied URLs (#2242). The API key is only ever sent
# to the API host; documents may come from Congress.gov or GovInfo.
CONGRESS_API_HOSTS = ("api.congress.gov",)
CONGRESS_DOCUMENT_HOSTS = (
    "api.congress.gov",
    "congress.gov",
    "www.congress.gov",
    "govinfo.gov",
    "www.govinfo.gov",
)


def fetch_congress_document(url: str):
    """GET a caller-supplied Congress.gov or GovInfo document URL safely.

    Raises UnsafeUrlError for any URL or redirect outside the allowlist.
    """
    # pylint: disable=import-outside-toplevel
    from openbb_core.provider.utils.url_safety import make_safe_request

    return make_safe_request(url.strip(), CONGRESS_DOCUMENT_HOSTS)


async def congress_api_request(url: str, api_key: str, **kwargs):
    """GET an api.congress.gov URL with the API key attached.

    The URL, and every redirect hop, must be on api.congress.gov, so the key
    can never be sent to a caller-chosen host. Raises UnsafeUrlError otherwise.
    """
    # pylint: disable=import-outside-toplevel
    from openbb_core.provider.utils.url_safety import amake_safe_request

    separator = "&" if "?" in url else "?"
    return await amake_safe_request(
        f"{url}{separator}api_key={api_key}", CONGRESS_API_HOSTS, **kwargs
    )
