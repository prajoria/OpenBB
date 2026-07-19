"""Commodity Futures Trading Commission (CFTC) Router."""

# pylint: disable=W0212,W0613

import logging
from typing import Any

from openbb_core.app.model.command_context import CommandContext
from openbb_core.app.model.example import APIEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.provider_interface import (
    ExtraParams,
    ProviderChoices,
    StandardParams,
)
from openbb_core.app.query import Query
from openbb_core.app.router import Router

logger = logging.getLogger(__name__)

router = Router(prefix="")
COT_CHOICES: list[dict[str, str | dict[str, str | None]]] = []


async def build_choices():
    """Build the choices for Workspace.

    Fetches the COT contract list from CFTC on FastAPI startup and
    caches it in ``COT_CHOICES``. Failure to fetch or parse (upstream
    503, HTML error page, network timeout, unexpected null fields, ...)
    MUST NOT prevent the REST API from starting — the choices are a
    UX nicety for Workspace's dropdown, not a hard runtime dependency.
    Degrade to an empty list and log an error so operators can triage.
    #874, #902.
    """
    # pylint: disable=import-outside-toplevel
    from openbb_cftc.models.cot_search import CftcCotSearchFetcher

    global COT_CHOICES  # noqa: PLW0603  # pylint: disable=W0603

    try:
        contracts = await CftcCotSearchFetcher.fetch_data({}, {})
    except Exception as exc:  # pylint: disable=broad-except
        # publicreporting.cftc.gov returns HTML on 503; aiohttp raises
        # ContentTypeError. Any of ClientError, TimeoutError, or JSON
        # decode errors during startup would crash uvicorn. Catch
        # broadly + log so the API still boots. Operators can either
        # restart later or re-invoke `build_choices` out-of-band.
        logger.error(
            "cftc.build_choices: upstream fetch failed — starting with "
            "empty COT_CHOICES so the API still boots. Error: %r",
            exc,
        )
        COT_CHOICES = []
        return

    # Parse-path guard (#902): even with a healthy fetch, per-record
    # fields can be null (the pydantic model declares
    # ``subcategory: str | None`` etc.). Skip any record missing the
    # required identifiers, and null-safe the strips so a null
    # subcategory doesn't crash the whole startup. Wrapped in a broad
    # try/except so any future field-shape regression at the record
    # level also degrades to an empty cache rather than killing the
    # API — mirrors the fetch-path degrade pattern from #874.
    choices: list[dict[str, str | dict[str, str | None]]] = []
    try:
        for d in contracts:
            # Required identifiers: skip records where either is null.
            # A choice without a label or value is useless to Workspace.
            if not d.name or not d.code:
                continue
            name = d.name.strip()
            code = d.code.strip()
            subcategory = (d.subcategory or "").strip()
            choice: dict[str, str | dict[str, str | None]] = {
                "label": name,
                "value": code,
                "extraInfo": {
                    "description": f"{subcategory}  | {code}",
                    "rightOfDescription": "",
                },
            }
            choices.append(choice)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error(
            "cftc.build_choices: record parsing failed — starting with "
            "empty COT_CHOICES so the API still boots. Error: %r",
            exc,
        )
        COT_CHOICES = []
        return

    COT_CHOICES = choices


router.api_router.add_event_handler("startup", build_choices)


async def get_cot_choices() -> list[dict[str, str | dict[str, str | None]]]:
    """Get the choices for the COT command in Workspace."""
    return COT_CHOICES


router._api_router.add_api_route(
    path="/get_cot_choices",
    endpoint=get_cot_choices,
    methods=["GET"],
    include_in_schema=False,
)


@router.command(
    model="COTSearch",
    examples=[
        APIEx(parameters={"provider": "cftc"}),
        APIEx(parameters={"query": "gold", "provider": "cftc"}),
    ],
    widget_config={
        "name": "Commitment of Traders Search",
        "description": "Search for CFTC Commitment of Traders (COT) report series.",
        "category": "CFTC",
        "subCategory": "COT",
        "refetchInterval": False,
    },
)
async def cot_search(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Search current Commitment of Traders Reports."""
    return await OBBject.from_query(Query(**locals()))


@router.command(
    model="COT",
    examples=[
        APIEx(parameters={"provider": "ctfc"}),
        APIEx(
            description="Get the latest report for all items classified as, GOLD.",
            parameters={"code": "CFTC_088691", "limit": 1, "provider": "cftc"},
        ),
        APIEx(
            description="Get the report for futures only.",
            parameters={
                "code": "CFTC_088691",
                "futures_only": True,
                "limit": 1,
                "provider": "cftc",
            },
        ),
        APIEx(
            description="Filter the report down to a specific section.",
            parameters={
                "code": "CFTC_088691",
                "futures_only": True,
                "measure": "changes",
                "limit": 1,
                "provider": "cftc",
            },
        ),
    ],
    widget_config={
        "name": "Commitment of Traders",
        "description": "CFTC Commitment of Traders (COT) reports.",
        "category": "CFTC",
        "subCategory": "COT",
        "refetchInterval": False,
    },
)
async def cot(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get Commitment of Traders Reports."""
    return await OBBject.from_query(Query(**locals()))


async def get_cftc_apps_json() -> list[dict[str, Any]]:
    """Get the IMF apps.json file.

    This endpoint serves the apps.json file containing OpenBB Workspace app configurations.
    It is automatically merged with any existing apps.json files in the Workspace and API.

    Returns
    -------
    list[dict[str, Any]]
        A list of OpenBB Workspace app configurations.
    """
    # pylint: disable=import-outside-toplevel
    import json
    from pathlib import Path

    apps_file = Path(__file__).parent / "apps.json"

    try:
        with apps_file.open("r", encoding="utf-8") as f:
            apps_json = json.load(f)
            return apps_json
    except Exception:
        return []


router._api_router.add_api_route(
    path="/apps.json",
    endpoint=get_cftc_apps_json,
    methods=["GET"],
    include_in_schema=False,
)
