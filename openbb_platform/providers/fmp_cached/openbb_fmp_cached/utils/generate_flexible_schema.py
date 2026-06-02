"""
Intelligent schema generator that creates tables based on actual model fields.
This creates a generic table structure that can handle any entity data.
"""

import os
from typing import Dict, List


def create_generic_entity_table(table_name: str) -> str:
    """Create a generic table that can store any entity data with JSON columns."""
    return f"""
def create_{table_name}_table():
    \"""Create {table_name} table for flexible data storage.\"""
    query = \"""
    CREATE TABLE IF NOT EXISTS {table_name} (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        
        -- Common identifier fields (indexed for performance)
        symbol VARCHAR(50) DEFAULT NULL,
        date DATE DEFAULT NULL,
        period VARCHAR(20) DEFAULT NULL,
        currency VARCHAR(10) DEFAULT NULL,
        exchange VARCHAR(50) DEFAULT NULL,
        
        -- Flexible data storage (JSON for complex structures)
        data_json JSON NOT NULL,
        
        -- Query parameters used to fetch this data
        query_params JSON DEFAULT NULL,
        
        -- Standard metadata
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_valid BOOLEAN DEFAULT TRUE,
        
        -- Performance indexes
        INDEX idx_symbol (symbol),
        INDEX idx_date (date),
        INDEX idx_symbol_date (symbol, date),
        INDEX idx_period (period),
        INDEX idx_currency (currency),
        INDEX idx_exchange (exchange),
        INDEX idx_cached_at (cached_at),
        INDEX idx_is_valid (is_valid),
        
        -- JSON indexes for common queries
        INDEX idx_data_symbol ((CAST(data_json->'$.symbol' AS CHAR(50)))),
        INDEX idx_data_date ((CAST(data_json->'$.date' AS DATE)))
        
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    \"""
    return _execute_query_env_aware(query)
"""


def get_all_model_entities():
    """Get all model entities from the cached provider."""
    models_dir = "/home/daaji/masterswork/git/OpenBB/openbb_platform/providers/fmp_cached/openbb_fmp_cached/models"
    entities = []
    
    for file in os.listdir(models_dir):
        if file.endswith('.py') and file not in ['__init__.py', 'base_cached.py']:
            entity_name = file[:-3]  # Remove .py extension
            entities.append(entity_name)
    
    return sorted(entities)


def generate_complete_flexible_schema():
    """Generate a complete schema with flexible JSON-based tables for all entities."""
    
    entities = get_all_model_entities()
    print(f"🔍 Found {len(entities)} model entities")
    
    schema_content = '''"""
Complete Flexible Database Schema for FMP Cached Provider

Auto-generated database tables for all FMP model entities using JSON storage.
This approach is flexible and can handle any data structure without schema changes.
Simple database-backed response persistence without TTL/caching complexity.
"""

from .database import execute_query, is_jupyter_mode, run_async_in_thread, execute_query_async


def _execute_query_env_aware(query: str, params: tuple = ()):
    """Execute query with environment detection."""
    if is_jupyter_mode():
        # In Jupyter, use sync version
        return execute_query(query, params)
    else:
        # In async environment, use async version
        return run_async_in_thread(execute_query_async(query, params))


'''
    
    # Generate table creation functions for each entity
    flattened_tables = {}
    
    for entity in entities:
        table_schema = create_generic_entity_table(entity)
        schema_content += table_schema + '\n\n'
        flattened_tables[entity] = {'schema': f"create_{entity}_table"}
    
    # Add FLATTENED_TABLES configuration
    schema_content += f'''
# Complete table configuration for all {len(flattened_tables)} entities
FLATTENED_TABLES = {{
'''
    
    for entity in sorted(flattened_tables.keys()):
        schema_content += f'''    "{entity}": {{
        "schema": create_{entity}_table
    }},
'''
    
    schema_content += '''}


def create_all_flattened_tables():
    """Create all flattened database tables."""
    results = {}
    print(f"Creating {len(FLATTENED_TABLES)} database tables...")
    
    for table_name, config in FLATTENED_TABLES.items():
        try:
            result = config["schema"]()
            results[table_name] = result
            print(f"✅ Created table: {table_name}")
        except Exception as e:
            results[table_name] = f"Error: {str(e)}"
            print(f"❌ Error creating {table_name}: {e}")
    
    return results


def create_all_tables():
    """Create all database tables (alias for create_all_flattened_tables)."""
    return create_all_flattened_tables()


def cleanup_expired_cache():
    """Cleanup function - no longer needed as we don't use TTL/expiry."""
    # Since we simplified to remove TTL/expiry, this function is a no-op
    return {"message": "No cleanup needed - TTL/expiry removed from simplified schema"}


def get_table_names():
    """Get all table names for the cached provider."""
    return list(FLATTENED_TABLES.keys())


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the schema."""
    return table_name in FLATTENED_TABLES
'''
    
    return schema_content, len(flattened_tables), entities


if __name__ == "__main__":
    schema_content, table_count, entities = generate_complete_flexible_schema()
    
    print(f"\\n📋 Entities found:")
    for i, entity in enumerate(entities, 1):
        print(f"  {i:2d}. {entity}")
    
    # Write to file
    output_file = "/home/daaji/masterswork/git/OpenBB/openbb_platform/providers/fmp_cached/openbb_fmp_cached/utils/cache_schema_all_entities.py"
    with open(output_file, 'w') as f:
        f.write(schema_content)
    
    print(f"\\n🎉 Generated complete flexible schema with {table_count} tables!")
    print(f"📄 Schema written to: cache_schema_all_entities.py")
    print(f"\\n💡 This approach uses JSON storage for flexibility:")
    print(f"   - Each entity gets its own table")
    print(f"   - Data stored as JSON for any structure")
    print(f"   - Common fields indexed for performance")
    print(f"   - No schema changes needed for new fields")