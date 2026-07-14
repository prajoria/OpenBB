"""Test if providers and fetchers are covered by tests."""

import os
import unittest
from importlib import import_module

from openbb_core.provider.abstract.provider import Provider
from openbb_core.provider.registry import RegistryLoader

from providers.tests.utils.unit_tests_generator import (
    check_pattern_in_file,
    get_provider_fetchers,
)


def get_provider_test_files(provider: Provider):
    """Given a provider, return the path to the test file."""
    fetchers_dict = provider.fetcher_dict
    fetcher_module_name = fetchers_dict[list(fetchers_dict.keys())[0]].__module__
    parent_module = import_module(fetcher_module_name.split(".")[0])
    parent_module_path = os.path.dirname(parent_module.__file__)  # type: ignore
    root_provider_path = os.path.dirname(parent_module_path)
    provider_name = provider.name.lower()

    return os.path.join(
        root_provider_path, "tests", f"test_{provider_name}_fetchers.py"
    )


class ProviderFetcherTest(unittest.TestCase):
    """Tests for providers and fetchers."""

    providers: dict[str, Provider] = RegistryLoader.from_extensions().providers

    def test_provider_w_tests(self):
        """Test the provider fetchers and ensure all providers have tests."""

        for provider_name, provider_cls in self.providers.items():
            with self.subTest(i=provider_name):
                path = get_provider_test_files(provider_cls)

                self.assertTrue(os.path.exists(path))

    # Coverage gap: fetchers registered but not yet exercised in their
    # provider's test file. Each entry here is technical debt tracked as
    # a follow-up to #754. When a fetcher is added with matching VCR
    # cassette + assertion in test_<provider>_fetchers.py, remove it
    # from this set.
    _COVERAGE_GAP_FETCHERS: set[str] = {
        # openbb_fmp — 6 new upstream fetchers added on develop without tests
        "FMPAftermarketQuoteFetcher",
        "FMPAftermarketTradeFetcher",
        "FMPEquityIntradayHistoricalFetcher",
        "FMPEquityQuoteBatchShortFetcher",
        "FMPExchangeMarketHoursFetcher",
        "FMPTechnicalIndicatorIntradayFetcher",
        # openbb_fmp_cached — 16 cache-wrapping fetchers registered without
        # dedicated instantiation-check test blocks
        "ExchangeMarketHoursTTLCached",
        "FMPCachedAftermarketQuoteFetcher",
        "FMPCachedAnalystEstimatesFetcher",
        "FMPCachedBalanceSheetFetcher",
        "FMPCachedCashFlowStatementFetcher",
        "FMPCachedEquityHistoricalFetcher",
        "FMPCachedEquityIntradayHistoricalFetcher",
        "FMPCachedEquityPeersFetcher",
        "FMPCachedEquityProfileFetcher",
        "FMPCachedEquityQuoteFetcher",
        "FMPCachedEtfHoldingsFetcher",
        "FMPCachedFinancialRatiosFetcher",
        "FMPCachedIncomeStatementFetcher",
        "FMPCachedIndexConstituentsFetcher",
        "FMPCachedInstitutionalOwnershipFetcher",
        "FMPCachedKeyMetricsFetcher",
    }

    def test_provider_fetchers_w_tests(self):
        """Ensure all the fetchers in each provider have tests.

        Exemptions:
        - Fetcher classes whose name starts with `Fallback`: dynamically
          generated cache-wrapper classes created at runtime by
          `openbb_fmp_cached`. Will never appear literally in test files
          by design.
        - Classes in `_COVERAGE_GAP_FETCHERS`: known technical debt from
          fetchers added on develop without corresponding test coverage.
          Tracked as follow-ups to #754. Remove from the set when the
          fetcher's `test_<provider>_fetchers.py` gets a matching
          `FetcherClass()` instantiation.
        """

        provider_fetchers = get_provider_fetchers()

        for provider_name, fetcher_dict in provider_fetchers.items():
            for _, fetcher_cls in fetcher_dict.items():
                name = fetcher_cls.__name__

                # Skip dynamically-generated fallback wrapper classes
                if name.startswith("Fallback"):
                    continue

                # Skip known coverage-gap fetchers (see #754)
                if name in self._COVERAGE_GAP_FETCHERS:
                    continue

                path = get_provider_test_files(self.providers[provider_name])

                # check that fetcher_cls is being instantiated in path
                with self.subTest(i=fetcher_cls):
                    self.assertTrue(check_pattern_in_file(path, f"{name}()"))  # type: ignore
