"""Corporate, SEC, IPO, M&A and fundraising routes."""

# ruff: noqa: D103
# pylint: disable=unused-argument

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request
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

router = Router(prefix="", description="FMP corporate and SEC reference data.")


async def _dispatch(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await OBBject.from_query(
        Query(
            cc=cc,
            provider_choices=provider_choices,
            standard_params=standard_params,
            extra_params=extra_params,
        )
    )


def _reject_unknown(
    arguments: set[str],
    cached_arguments: set[str] | None = None,
) -> Callable:
    async def dependency(request: Request) -> None:
        provider = request.query_params.get("provider")
        allowed = (
            cached_arguments
            if provider == "fmp_cached" and cached_arguments is not None
            else arguments
        )
        unknown = set(request.query_params) - {"provider"} - allowed
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown query arguments: {', '.join(sorted(unknown))}",
            )

    return dependency


def _command(
    model: str,
    description: str,
    arguments: set[str],
    cached_arguments: set[str] | None = None,
):
    def decorator(func):
        func.__doc__ = description
        parameters = {"provider": "fmp_cached"}
        for argument, value in (
            ("symbol", "AAPL"),
            ("cik", "0000320193"),
            ("name", "Alpha Holdings"),
        ):
            if argument in (cached_arguments or arguments):
                parameters[argument] = value
        return router.command(
            model=model,
            operation_id=f"fmp_cached_{func.__name__}",
            dependencies=[Depends(_reject_unknown(arguments, cached_arguments))],
            examples=[APIEx(parameters=parameters)],
            widget_config={
                "name": func.__name__.replace("_", " ").title(),
                "description": description,
                "category": "FMP Cached",
                "subCategory": "Corporate",
                "refetchInterval": False,
            },
        )(func)

    return decorator


@_command(
    "AcquisitionOfBeneficialOwnership",
    "Get beneficial ownership acquisitions.",
    {"symbol"},
)
async def acquisition_of_beneficial_ownership(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("AllIndustryClassification", "List all industry classifications.", set())
async def all_industry_classification(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("CrowdfundingOfferings", "Get crowdfunding offerings by CIK.", {"cik"})
async def crowdfunding_offerings(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "CrowdfundingOfferingsLatest",
    "Get latest crowdfunding offerings.",
    {"page", "limit"},
    set(),
)
async def crowdfunding_offerings_latest(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("CrowdfundingOfferingsSearch", "Search crowdfunding offerings.", {"name"})
async def crowdfunding_offerings_search(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("DelistedCompanies", "List delisted companies.", {"page", "limit"}, set())
async def delisted_companies(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("Fundraising", "Get fundraising records by CIK.", {"cik"})
async def fundraising(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "FundraisingLatest", "Get latest fundraising records.", {"page", "limit"}, set()
)
async def fundraising_latest(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("FundraisingSearch", "Search fundraising records.", {"name"})
async def fundraising_search(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "IndustryClassificationSearch",
    "Search industry classifications.",
    {"symbol", "cik", "sicCode"},
    {"symbol"},
)
async def industry_classification_search(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("IposDisclosure", "List IPO disclosures.", {"page", "limit"}, set())
async def ipos_disclosure(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("IposProspectus", "List IPO prospectus records.", {"page", "limit"}, set())
async def ipos_prospectus(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "MergersAcquisitionsLatest",
    "Get latest M&A records.",
    {"page", "limit"},
    set(),
)
async def mergers_acquisitions_latest(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("MergersAcquisitionsSearch", "Search M&A records.", {"name"})
async def mergers_acquisitions_search(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command(
    "SecFilings8K",
    "List SEC 8-K filings by page.",
    {"from", "to", "page", "limit"},
    {"page"},
)
async def sec_filings_8k(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("SecProfile", "Get an SEC company profile.", {"symbol"})
async def sec_profile(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())


@_command("StandardIndustrialClassificationList", "List SIC references.", set())
async def standard_industrial_classification_list(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await _dispatch(**locals())
