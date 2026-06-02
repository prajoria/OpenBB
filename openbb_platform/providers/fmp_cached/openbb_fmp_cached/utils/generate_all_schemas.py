"""
Generate database tables for all FMP cached provider models.

This script analyzes all model files and generates corresponding database table schemas.
"""

import os
import ast
import re
from typing import Dict, List, Set

def get_model_files():
    """Get all model Python files."""
    models_dir = "/home/daaji/masterswork/git/OpenBB/openbb_platform/providers/fmp_cached/openbb_fmp_cached/models"
    model_files = []
    
    for file in os.listdir(models_dir):
        if file.endswith('.py') and file not in ['__init__.py', 'base_cached.py']:
            model_files.append(file[:-3])  # Remove .py extension
    
    return sorted(model_files)

def analyze_model_file(model_name: str) -> Dict:
    """Analyze a model file to extract field information."""
    file_path = f"/home/daaji/masterswork/git/OpenBB/openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/{model_name}.py"
    
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Extract class definitions and field annotations
        fields = {}
        
        # Look for field definitions in classes
        field_pattern = r'(\w+):\s*Optional\[([\w\[\], ]+)\]|(\w+):\s*([\w\[\], ]+)'
        matches = re.findall(field_pattern, content)
        
        for match in matches:
            if match[0]:  # Optional field
                field_name = match[0]
                field_type = match[1]
            elif match[2]:  # Regular field
                field_name = match[2]
                field_type = match[3]
            else:
                continue
            
            # Skip special fields
            if field_name in ['self', 'cls', '__annotations__', '__module__']:
                continue
            
            fields[field_name] = field_type
        
        return {
            'table_name': model_name,
            'fields': fields,
            'file_path': file_path
        }
        
    except Exception as e:
        return {
            'table_name': model_name,
            'fields': {},
            'error': str(e)
        }

def map_python_type_to_sql(python_type: str) -> str:
    """Map Python type annotations to SQL column types."""
    # Clean up the type string
    python_type = python_type.strip()
    python_type = re.sub(r'\s+', '', python_type)  # Remove whitespace
    
    # Handle Union types and Optional
    if 'Union[' in python_type or 'Optional[' in python_type:
        # Extract the main type (usually the first non-None type)
        inner_match = re.search(r'\[(.*?)\]', python_type)
        if inner_match:
            types = inner_match.group(1).split(',')
            for t in types:
                t = t.strip()
                if t != 'None' and t != 'type[None]':
                    python_type = t
                    break
    
    # Remove List wrapper
    if python_type.startswith('List[') or python_type.startswith('list['):
        # For list types, we'll store as JSON or create separate tables
        return 'JSON'
    
    # Map basic types
    type_mapping = {
        'str': 'VARCHAR(255)',
        'string': 'VARCHAR(255)', 
        'int': 'INT',
        'integer': 'INT',
        'float': 'DECIMAL(15,6)',
        'bool': 'BOOLEAN',
        'boolean': 'BOOLEAN',
        'date': 'DATE',
        'datetime': 'DATETIME',
        'Timestamp': 'TIMESTAMP',
        'Any': 'TEXT',
        'Dict': 'JSON',
        'dict': 'JSON'
    }
    
    # Check for exact matches first
    if python_type in type_mapping:
        return type_mapping[python_type]
    
    # Check for partial matches
    python_type_lower = python_type.lower()
    for py_type, sql_type in type_mapping.items():
        if py_type.lower() in python_type_lower:
            return sql_type
    
    # Default to TEXT for unknown types
    return 'TEXT'

def generate_table_schema(model_info: Dict) -> str:
    """Generate CREATE TABLE SQL for a model."""
    table_name = model_info['table_name']
    fields = model_info['fields']
    
    if not fields:
        return f"-- No fields found for {table_name}"
    
    # Start building the schema
    schema_lines = [
        f"def create_{table_name}_table():",
        f'    """Create {table_name} table for {table_name.replace("_", " ")} data."""',
        '    query = """',
        f'    CREATE TABLE IF NOT EXISTS {table_name} (',
        '        id BIGINT AUTO_INCREMENT PRIMARY KEY,'
    ]
    
    # Add fields
    for field_name, field_type in fields.items():
        sql_type = map_python_type_to_sql(field_type)
        schema_lines.append(f'        {field_name} {sql_type},')
    
    # Add standard metadata columns
    schema_lines.extend([
        '',
        '        -- Simple metadata',
        '        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,', 
        '        is_valid BOOLEAN DEFAULT TRUE,',
        '',
        '        INDEX idx_cached_at (cached_at),',
        '        INDEX idx_is_valid (is_valid)'
    ])
    
    # Add indexes for common fields
    common_index_fields = ['symbol', 'date', 'period', 'currency', 'exchange']
    for field in common_index_fields:
        if field in fields:
            schema_lines.append(f'        INDEX idx_{field} ({field}),')
    
    # Remove trailing comma and close table
    if schema_lines[-1].endswith(','):
        schema_lines[-1] = schema_lines[-1][:-1]  # Remove trailing comma
    
    schema_lines.extend([
        '    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci',
        '    """',
        '    return _execute_query_env_aware(query)',
        ''
    ])
    
    return '\n'.join(schema_lines)

def generate_complete_schema_file():
    """Generate complete schema file with all model tables."""
    print("🔍 Analyzing all model files...")
    
    model_files = get_model_files()
    print(f"Found {len(model_files)} model files")
    
    # Analyze each model
    model_info = []
    for model_name in model_files:
        print(f"  📋 Analyzing {model_name}...")
        info = analyze_model_file(model_name)
        model_info.append(info)
        
        if 'error' in info:
            print(f"    ⚠️  Error: {info['error']}")
        else:
            print(f"    ✅ Found {len(info['fields'])} fields")
    
    # Generate schema file
    print("\n🏗️  Generating complete schema file...")
    
    schema_content = '''"""
Complete Database Schema for FMP Cached Provider

Auto-generated database tables for all FMP model entities.
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
    for info in model_info:
        if 'error' not in info and info['fields']:
            table_schema = generate_table_schema(info)
            schema_content += table_schema + '\n\n'
            flattened_tables[info['table_name']] = {'schema': f"create_{info['table_name']}_table"}
    
    # Add FLATTENED_TABLES configuration
    schema_content += f'''
# Complete table configuration for all {len(flattened_tables)} entities
FLATTENED_TABLES = {{
'''
    
    for table_name in sorted(flattened_tables.keys()):
        schema_content += f'''    "{table_name}": {{
        "schema": create_{table_name}_table
    }},
'''
    
    schema_content += '''}


def create_all_flattened_tables():
    """Create all flattened database tables."""
    results = {}
    for table_name, config in FLATTENED_TABLES.items():
        try:
            result = config["schema"]()
            results[table_name] = result
        except Exception as e:
            results[table_name] = f"Error: {str(e)}"
    return results


def create_all_tables():
    """Create all database tables (alias for create_all_flattened_tables)."""
    return create_all_flattened_tables()


def cleanup_expired_cache():
    """Cleanup function - no longer needed as we don't use TTL/expiry."""
    # Since we simplified to remove TTL/expiry, this function is a no-op
    return {"message": "No cleanup needed - TTL/expiry removed from simplified schema"}
'''
    
    return schema_content, len(flattened_tables)

if __name__ == "__main__":
    schema_content, table_count = generate_complete_schema_file()
    
    # Write to file
    output_file = "/home/daaji/masterswork/git/OpenBB/openbb_platform/providers/fmp_cached/openbb_fmp_cached/utils/cache_schema_complete.py"
    with open(output_file, 'w') as f:
        f.write(schema_content)
    
    print(f"\n🎉 Generated complete schema with {table_count} tables!")
    print(f"📄 Schema written to: cache_schema_complete.py")