#!/usr/bin/env bash
# gen-test.sh - Scaffold test files following project conventions

set -euo pipefail

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

PROJECT_ROOT="/c/laragon/www/agenteWhatsapp"
cd "$PROJECT_ROOT"

VALID_MODULES=("reservations" "availability" "customers" "reminders" "faqs")
VALID_TYPES=("models" "service" "tools" "router")

usage() {
    echo -e "${RED}Usage: $0 <module> <type> [test-name]${NC}"
    echo ""
    echo "Modules: ${VALID_MODULES[*]}"
    echo "Types:   ${VALID_TYPES[*]}"
    echo ""
    echo "Examples:"
    echo "  $0 reservations service"
    echo "  $0 availability tools test_find_available_tables"
    exit 1
}

if [ $# -lt 2 ]; then
    usage
fi

MODULE="$1"
TYPE="$2"
TEST_NAME="${3:-}"

# Validate module
if [[ ! " ${VALID_MODULES[*]} " =~ " ${MODULE} " ]]; then
    echo -e "${RED}Invalid module: $MODULE${NC}"
    usage
fi

# Validate type
if [[ ! " ${VALID_TYPES[*]} " =~ " ${TYPE} " ]]; then
    echo -e "${RED}Invalid type: $TYPE${NC}"
    usage
fi

# Determine test file path
TEST_DIR="tests/modules/$MODULE"
TEST_FILE="$TEST_DIR/test_${TYPE}.py"

if [ -n "$TEST_NAME" ]; then
    TEST_FILE="$TEST_DIR/test_${TYPE}_${TEST_NAME}.py"
fi

# Create directory if needed
mkdir -p "$TEST_DIR"

# Create __init__.py if not exists
touch "$TEST_DIR/__init__.py"

# Check if file exists
if [ -f "$TEST_FILE" ]; then
    echo -e "${YELLOW}File exists: $TEST_FILE${NC}"
    echo -e "${YELLOW}Overwrite? (y/N)${NC}"
    read -r OVERWRITE
    if [[ ! "$OVERWRITE" =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
fi

echo -e "${GREEN}Creating test scaffold: $TEST_FILE${NC}"

# Generate test content based on type
cat > "$TEST_FILE" << 'EOF'
"""Tests for {{MODULE}}.{{TYPE}}"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# Module imports
EOF

# Replace placeholders and add type-specific content
case "$TYPE" in
    "models")
        cat >> "$TEST_FILE" << 'EOF'
from app.modules.{{MODULE}}.models import *

@pytest.mark.asyncio
async def test_{{MODULE}}_model_creation(db_session: AsyncSession):
    """Test basic model creation and persistence."""
    # TODO: Add model-specific tests
    pass

@pytest.mark.asyncio
async def test_{{MODULE}}_model_relationships(db_session: AsyncSession):
    """Test model relationships and constraints."""
    # TODO: Add relationship tests
    pass
EOF
        ;;
    "service")
        cat >> "$TEST_FILE" << 'EOF'
from app.modules.{{MODULE}}.service import *

@pytest.mark.asyncio
async def test_{{MODULE}}_service_basic(db_session: AsyncSession):
    """Test basic service operations."""
    # TODO: Add service tests
    pass

@pytest.mark.asyncio
async def test_{{MODULE}}_service_multi_tenant(db_session: AsyncSession):
    """Test multi-tenant isolation (restaurant_id filtering)."""
    # TODO: Verify restaurant_id is always filtered
    pass
EOF
        ;;
    "tools")
        cat >> "$TEST_FILE" << 'EOF'
from app.modules.{{MODULE}}.tools import *

@pytest.mark.asyncio
async def test_{{MODULE}}_tool_basic():
    """Test tool function directly."""
    # TODO: Add tool tests
    pass

@pytest.mark.asyncio
async def test_{{MODULE}}_tool_error_handling():
    """Test tool error cases."""
    # TODO: Add error handling tests
    pass
EOF
        ;;
    "router")
        cat >> "$TEST_FILE" << 'EOF'
from app.modules.{{MODULE}}.router import *

@pytest.mark.asyncio
async def test_{{MODULE}}_router_endpoints(async_client: AsyncClient, auth_headers: dict):
    """Test router endpoints with JWT auth."""
    # TODO: Add endpoint tests
    pass

@pytest.mark.asyncio
async def test_{{MODULE}}_router_unauthorized(async_client: AsyncClient):
    """Test endpoints reject unauthorized requests."""
    # TODO: Add 401 tests
    pass
EOF
        ;;
esac

# Replace {{MODULE}} placeholder
sed -i "s/{{MODULE}}/$MODULE/g" "$TEST_FILE"

echo -e "${GREEN}Created: $TEST_FILE${NC}"
echo -e "${BLUE}Next steps:${NC}"
echo "1. Add test cases for your specific functionality"
echo "2. Run: pytest $TEST_FILE -v"
echo "3. Check coverage: pytest --cov=app.modules.$MODULE $TEST_FILE"