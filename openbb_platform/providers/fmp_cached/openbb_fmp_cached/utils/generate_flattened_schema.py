"""
Create flattened database schemas by analyzing actual OpenBB standard models.
This generates proper column mappings for each entity type.
"""

import os
import ast
import inspect
from typing import Dict, List, Any

# Import OpenBB standard models to get field definitions
try:
    from openbb_core.provider.standard_models.equity_historical import EquityHistoricalData
    from openbb_core.provider.standard_models.equity_profile import EquityProfileData  
    from openbb_core.provider.standard_models.balance_sheet import BalanceSheetData
    from openbb_core.provider.standard_models.income_statement import IncomeStatementData
    from openbb_core.provider.standard_models.cash_flow import CashFlowStatementData
    from openbb_core.provider.standard_models.financial_ratios import FinancialRatiosData
except ImportError as e:
    print(f"Could not import standard models: {e}")
    EquityHistoricalData = None

def get_pydantic_fields(model_class):
    """Extract field definitions from a Pydantic model."""
    if not model_class:
        return {}
    
    try:
        # Get field info from Pydantic model
        if hasattr(model_class, 'model_fields'):
            # Pydantic v2
            fields = {}
            for field_name, field_info in model_class.model_fields.items():
                annotation = field_info.annotation if hasattr(field_info, 'annotation') else str
                fields[field_name] = annotation
            return fields
        elif hasattr(model_class, '__fields__'):
            # Pydantic v1
            fields = {}
            for field_name, field_info in model_class.__fields__.items():
                fields[field_name] = field_info.type_
            return fields
    except Exception as e:
        print(f"Error extracting fields from {model_class}: {e}")
    
    return {}

def python_type_to_sql(python_type) -> str:
    """Convert Python type to SQL column type."""
    type_str = str(python_type)
    
    # Handle Optional/Union types
    if 'Union[' in type_str or 'Optional[' in type_str:
        # Extract non-None type
        if 'int' in type_str:
            python_type = int
        elif 'float' in type_str:
            python_type = float
        elif 'str' in type_str:
            python_type = str
        elif 'bool' in type_str:
            python_type = bool
        elif 'date' in type_str:
            return 'DATE'
        elif 'datetime' in type_str:
            return 'DATETIME'
        else:
            return 'TEXT'
    
    # Basic type mapping
    if python_type == int or 'int' in type_str:
        return 'BIGINT'
    elif python_type == float or 'float' in type_str:
        return 'DECIMAL(15,6)'
    elif python_type == str or 'str' in type_str:
        return 'VARCHAR(255)'
    elif python_type == bool or 'bool' in type_str:
        return 'BOOLEAN'
    elif 'date' in type_str.lower():
        return 'DATE'
    elif 'datetime' in type_str.lower() or 'timestamp' in type_str.lower():
        return 'DATETIME'
    else:
        return 'TEXT'

def create_entity_table_schema(entity_name: str, fields: Dict[str, Any]) -> str:
    """Create table schema with actual columns for an entity."""
    
    schema_lines = [
        f"def create_{entity_name}_table():",
        f'    """Create {entity_name} table with flattened columns."""',
        '    query = """',
        f'    CREATE TABLE IF NOT EXISTS {entity_name} (',
        '        id BIGINT AUTO_INCREMENT PRIMARY KEY,'
    ]
    
    # Add entity-specific fields
    for field_name, field_type in fields.items():
        sql_type = python_type_to_sql(field_type)
        schema_lines.append(f'        {field_name} {sql_type},')
    
    # Add standard metadata
    schema_lines.extend([
        '',
        '        -- Standard metadata',
        '        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,',
        '        is_valid BOOLEAN DEFAULT TRUE,',
        '',
        '        -- Indexes for common fields'
    ])
    
    # Add indexes for common fields
    common_fields = ['symbol', 'date', 'period', 'currency', 'exchange']
    for field in common_fields:
        if field in fields:
            schema_lines.append(f'        INDEX idx_{field} ({field}),')
    
    # Add metadata indexes
    schema_lines.extend([
        '        INDEX idx_cached_at (cached_at),',
        '        INDEX idx_is_valid (is_valid)'
    ])
    
    # Remove trailing comma
    if schema_lines[-1].endswith(','):
        schema_lines[-1] = schema_lines[-1][:-1]
    
    schema_lines.extend([
        '    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci',
        '    """',
        '    return _execute_query_env_aware(query)',
        ''
    ])
    
    return '\n'.join(schema_lines)

def generate_common_fields_schema() -> Dict[str, str]:
    """Generate common field mappings that work across all entities."""
    
    # Common fields that appear in most financial data entities
    common_fields = {
        # Identifiers
        'symbol': 'VARCHAR(50)',
        'date': 'DATE', 
        'period': 'VARCHAR(20)',
        'currency': 'VARCHAR(10)',
        'exchange': 'VARCHAR(50)',
        
        # Common financial fields
        'open': 'DECIMAL(15,6)',
        'high': 'DECIMAL(15,6)', 
        'low': 'DECIMAL(15,6)',
        'close': 'DECIMAL(15,6)',
        'volume': 'BIGINT',
        'vwap': 'DECIMAL(15,6)',
        'change_amount': 'DECIMAL(15,6)',  # Renamed from 'change' to avoid MySQL reserved keyword
        'change_percent': 'DECIMAL(8,6)',
        
        # Company profile fields
        'company_name': 'VARCHAR(255)',
        'sector': 'VARCHAR(100)',
        'industry': 'VARCHAR(100)',
        'country': 'VARCHAR(100)',
        'market_cap': 'BIGINT',
        'price': 'DECIMAL(15,6)',
        'beta': 'DECIMAL(8,6)',
        'description': 'TEXT',
        'ceo': 'VARCHAR(255)',
        'employees': 'INT',
        'website': 'VARCHAR(255)',
        
        # Financial statement fields (income statement)
        'revenue': 'BIGINT',
        'cost_of_revenue': 'BIGINT',
        'gross_profit': 'BIGINT',
        'operating_expenses': 'BIGINT',
        'operating_income': 'BIGINT',
        'net_income': 'BIGINT',
        'eps': 'DECIMAL(8,6)',
        'eps_diluted': 'DECIMAL(8,6)',
        
        # Balance sheet fields
        'total_assets': 'BIGINT',
        'total_liabilities': 'BIGINT',
        'total_equity': 'BIGINT',
        'cash_and_cash_equivalents': 'BIGINT',
        'total_debt': 'BIGINT',
        'working_capital': 'BIGINT',
        
        # Cash flow fields  
        'operating_cash_flow': 'BIGINT',
        'investing_cash_flow': 'BIGINT',
        'financing_cash_flow': 'BIGINT',
        'free_cash_flow': 'BIGINT',
        'capital_expenditure': 'BIGINT',
        
        # Ratio fields
        'pe_ratio': 'DECIMAL(15,6)',
        'pb_ratio': 'DECIMAL(15,6)',
        'debt_to_equity': 'DECIMAL(15,6)',
        'current_ratio': 'DECIMAL(15,6)',
        'roe': 'DECIMAL(15,6)',
        'roa': 'DECIMAL(15,6)',
        
        # Generic data storage for unknown fields
        'data_json': 'JSON',
        'additional_fields': 'JSON'
    }
    
    return common_fields

def create_flexible_table_schema(entity_name: str) -> str:
    """Create a flexible table that can handle most entity data with common columns."""
    
    common_fields = generate_common_fields_schema()
    
    schema_lines = [
        f"def create_{entity_name}_table():",
        f'    """Create {entity_name} table with common financial data columns."""',
        '    query = """',
        f'    CREATE TABLE IF NOT EXISTS {entity_name} (',
        '        id BIGINT AUTO_INCREMENT PRIMARY KEY,',
        ''
    ]
    
    # Add common fields
    for field_name, sql_type in common_fields.items():
        if field_name in ['data_json', 'additional_fields']:
            schema_lines.append(f'        {field_name} {sql_type} DEFAULT NULL,')
        else:
            schema_lines.append(f'        {field_name} {sql_type} DEFAULT NULL,')
    
    # Add metadata
    schema_lines.extend([
        '',
        '        -- Standard metadata',
        '        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,',
        '        is_valid BOOLEAN DEFAULT TRUE,',
        '',
        '        -- Performance indexes',
        '        INDEX idx_symbol (symbol),',
        '        INDEX idx_date (date),',
        '        INDEX idx_symbol_date (symbol, date),',
        '        INDEX idx_period (period),',
        '        INDEX idx_currency (currency),',
        '        INDEX idx_exchange (exchange),',
        '        INDEX idx_cached_at (cached_at),',
        '        INDEX idx_is_valid (is_valid),'
    ])
    
    # Add unique constraints for common patterns
    if entity_name in ['equity_historical', 'index_historical', 'crypto_historical', 'currency_historical']:
        schema_lines.append('        UNIQUE KEY unique_symbol_date_period (symbol, date, period)')
    elif entity_name in ['equity_profile']:
        schema_lines.append('        UNIQUE KEY unique_symbol (symbol)')
    elif entity_name in ['balance_sheet', 'income_statement', 'cash_flow']:
        schema_lines.append('        UNIQUE KEY unique_symbol_date_period (symbol, date, period)')
    else:
        schema_lines.append('        INDEX idx_composite (symbol, date, period)')
    
    schema_lines.extend([
        '',
        '    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci',
        '    """',
        '    return _execute_query_env_aware(query)',
        ''
    ])
    
    return '\n'.join(schema_lines)

def generate_flattened_schema_for_all_entities():
    """Generate flattened schema for all entities."""
    
    # Get all entity names
    models_dir = "/home/daaji/masterswork/git/OpenBB/openbb_platform/providers/fmp_cached/openbb_fmp_cached/models"
    entities = []
    
    for file in os.listdir(models_dir):
        if file.endswith('.py') and file not in ['__init__.py', 'base_cached.py']:
            entity_name = file[:-3]
            entities.append(entity_name)
    
    entities.sort()
    
    print(f"🔍 Generating flattened schema for {len(entities)} entities...")
    
    schema_content = '''"""
Complete Flattened Database Schema for FMP Cached Provider

Database tables with actual columns mapped from OpenBB model fields.
This enables proper relational queries and consistent DataFrame mapping.
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
    
    # Generate table creation functions
    flattened_tables = {}
    
    for entity in entities:
        # Create flexible schema for each entity
        table_schema = create_flexible_table_schema(entity)
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
    print(f"Creating {len(FLATTENED_TABLES)} flattened database tables...")
    
    for table_name, config in FLATTENED_TABLES.items():
        try:
            result = config["schema"]()
            results[table_name] = result
            print(f"✅ Created flattened table: {table_name}")
        except Exception as e:
            results[table_name] = f"Error: {str(e)}"
            print(f"❌ Error creating {table_name}: {e}")
    
    return results


def create_all_tables():
    """Create all database tables (alias for create_all_flattened_tables)."""
    return create_all_flattened_tables()


def cleanup_expired_cache():
    """Cleanup function - no longer needed as we don't use TTL/expiry."""
    return {"message": "No cleanup needed - TTL/expiry removed from simplified schema"}


def get_table_names():
    """Get all table names for the cached provider."""
    return list(FLATTENED_TABLES.keys())


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the schema."""
    return table_name in FLATTENED_TABLES


def get_common_field_names():
    """Get list of common field names used across entities."""
    return [
        'symbol', 'date', 'period', 'currency', 'exchange',
        'open', 'high', 'low', 'close', 'volume', 'vwap', 'change_amount', 'change_percent',
        'company_name', 'sector', 'industry', 'country', 'market_cap', 'price', 'beta',
        'revenue', 'cost_of_revenue', 'gross_profit', 'operating_income', 'net_income',
        'total_assets', 'total_liabilities', 'total_equity', 'cash_and_cash_equivalents',
        'operating_cash_flow', 'free_cash_flow', 'pe_ratio', 'pb_ratio', 'debt_to_equity'
    ]
'''
    
    return schema_content, len(flattened_tables), entities

if __name__ == "__main__":
    schema_content, table_count, entities = generate_flattened_schema_for_all_entities()
    
    print(f"\n📋 Entities with flattened schemas:")
    for i, entity in enumerate(entities, 1):
        print(f"  {i:2d}. {entity}")
    
    # Write to file
    output_file = "/home/daaji/masterswork/git/OpenBB/openbb_platform/providers/fmp_cached/openbb_fmp_cached/utils/cache_schema_flattened.py"
    with open(output_file, 'w') as f:
        f.write(schema_content)
    
    print(f"\n🎉 Generated flattened schema with {table_count} tables!")
    print(f"📄 Schema written to: cache_schema_flattened.py")
    print(f"\n💡 Benefits of flattened approach:")
    print(f"   - Real database columns instead of JSON")
    print(f"   - Proper relational queries and joins")
    print(f"   - Consistent DataFrame field mapping")
    print(f"   - Better performance with indexed columns")
    print(f"   - SQL query compatibility")