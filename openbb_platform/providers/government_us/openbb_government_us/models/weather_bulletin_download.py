"""Government US Weather Bulletin Download Model."""

# pylint: disable=unused-argument

from typing import Any

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.weather_bulletin_download import (
    WeatherBulletinDownloadData,
    WeatherBulletinDownloadQueryParams,
)
from pydantic import Field

# Exact host for caller-supplied bulletin URLs (#2242).
USDA_ESMIS_HOSTS = ("esmis.nal.usda.gov",)


class GovernmentUsWeatherBulletinDownloadQueryParams(
    WeatherBulletinDownloadQueryParams
):
    """US Government Weather Bulletin Download Query Params."""

    __json_schema_extra__ = {
        "urls": {
            "multiple_items_allowed": True,
        }
    }


class GovernmentUsWeatherBulletinDownloadData(WeatherBulletinDownloadData):
    """US Government Weather Bulletin Download Data."""

    data_format: dict[str, str] = Field(description="Data format information.")


class GovernmentUsWeatherBulletinDownloadFetcher(
    Fetcher[
        GovernmentUsWeatherBulletinDownloadQueryParams,
        list[GovernmentUsWeatherBulletinDownloadData],
    ]
):
    """US Government Weather Bulletin Download Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> GovernmentUsWeatherBulletinDownloadQueryParams:
        """Transform params into the query params model."""
        return GovernmentUsWeatherBulletinDownloadQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: GovernmentUsWeatherBulletinDownloadQueryParams,
        credentials: dict[str, Any] | None,
        **kwargs: Any,
    ) -> dict:
        """Extract the raw PDF content."""
        # pylint: disable=import-outside-toplevel
        from openbb_core.provider.utils.helpers import get_async_requests_session
        from openbb_core.provider.utils.url_safety import (
            amake_safe_request,
            validate_public_url,
        )

        results: dict = {}
        urls = query.urls

        # Verify every URL before downloading any (#2242): exact USDA ESMIS host,
        # https, default port, public address. Redirects are re-checked per hop.
        for url in urls:
            validate_public_url(url, USDA_ESMIS_HOSTS)
            if not url.lower().endswith(".pdf"):
                raise OpenBBError(
                    ValueError(
                        f"Invalid URL '{url}'. Only PDF documents are supported."
                    )
                )

        async def read_pdf(response, _session):
            if response.status != 200:
                raise OpenBBError(
                    ValueError(
                        f"Failed to download document from {response.url}."
                        f" Status code: {response.status}"
                    )
                )
            return await response.read()

        try:
            async with await get_async_requests_session() as session:
                session._max_field_size = 32768  # pylint: disable=protected-access

                for url in urls:
                    results[url] = await amake_safe_request(
                        url,
                        USDA_ESMIS_HOSTS,
                        session=session,
                        response_callback=read_pdf,
                    )

            return results
        except OpenBBError:
            raise
        except Exception as e:
            raise OpenBBError(e) from e

    @staticmethod
    def transform_data(
        query: GovernmentUsWeatherBulletinDownloadQueryParams,
        data: dict,
        **kwargs: Any,
    ) -> list[GovernmentUsWeatherBulletinDownloadData]:
        """Transform the raw PDF content into the data model."""
        # pylint: disable=import-outside-toplevel
        import base64

        output: list[GovernmentUsWeatherBulletinDownloadData] = []

        for url, content in data.items():
            content_b64 = base64.b64encode(content).decode("utf-8")
            data_format = {
                "data_type": "pdf",
                "filename": url.split("/")[-1],
            }
            bulletin_data = GovernmentUsWeatherBulletinDownloadData(
                content=content_b64,
                data_format=data_format,
            )
            output.append(bulletin_data)

        return output
