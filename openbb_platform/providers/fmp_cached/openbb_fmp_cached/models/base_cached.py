"""Base fallback for FMP cached models - provides only credential translation."""

import logging
from typing import Any, Dict, Type

from openbb_core.provider.abstract.fetcher import Fetcher

logger = logging.getLogger(__name__)

# NOTE: This base class provides only fallback functionality with credential translation.
# Each endpoint should implement its own dedicated database persistence logic in its specific model file.
# This is NOT caching - it's persistent database storage to avoid unnecessary API calls.


def create_fallback_fetcher_class(original_fetcher_class: Type[Fetcher], endpoint_name: str) -> Type[Fetcher]:
    """Create a fallback version of an FMP fetcher class with only credential translation.
    
    This is a simple fallback for endpoints that don't have dedicated database persistence.
    Each endpoint should implement its own database persistence logic in its specific model file.
    
    Args:
        original_fetcher_class: The original FMP fetcher class
        endpoint_name: Name of the endpoint for identification
        
    Returns:
        New fallback fetcher class with credential translation only
    """
    
    class FallbackFMPFetcher(original_fetcher_class):
        """Fallback FMP fetcher with credential translation only."""
        
        @staticmethod
        def transform_query(params: Dict[str, Any]):
            """Use original transform_query method."""
            return original_fetcher_class.transform_query(params)
        
        @staticmethod
        async def aextract_data(query, credentials, **kwargs):
            """Extract data with credential translation only - no database persistence."""
            print(f"⚠️  FALLBACK: Using fallback implementation for endpoint: {endpoint_name}")
            print(f"   Consider implementing dedicated database persistence in the specific model file")
            
            # Fix credential mapping: fmp_cached_api_key -> fmp_api_key
            if credentials and 'fmp_cached_api_key' in credentials:
                translated_credentials = {
                    'fmp_api_key': credentials['fmp_cached_api_key']
                }
            else:
                translated_credentials = credentials
            
            try:
                # Direct FMP API call with credential translation only
                raw_data = await original_fetcher_class.aextract_data(query, translated_credentials, **kwargs)
                return original_fetcher_class.transform_data(query, raw_data, **kwargs)
                
            except Exception as e:
                logger.error(f"Failed to fetch data from FMP for {endpoint_name}: {e}")
                raise
        
        @staticmethod
        def transform_data(query, data, **kwargs):
            """Use original transform_data method."""
            return original_fetcher_class.transform_data(query, data, **kwargs)
    
    # Set class name and module for better debugging
    FallbackFMPFetcher.__name__ = f"Fallback{original_fetcher_class.__name__}"
    FallbackFMPFetcher.__qualname__ = f"Fallback{original_fetcher_class.__qualname__}"
    
    return FallbackFMPFetcher


# Deprecated: Use create_fallback_fetcher_class instead
# This function is kept for backward compatibility only
def create_cached_fetcher_class(original_fetcher_class: Type[Fetcher], endpoint_name: str) -> Type[Fetcher]:
    """Deprecated: Use create_fallback_fetcher_class instead."""
    # logger.warning(f"create_cached_fetcher_class is deprecated for {endpoint_name}. Use dedicated database persistence in the specific model file.")
    return create_fallback_fetcher_class(original_fetcher_class, endpoint_name)