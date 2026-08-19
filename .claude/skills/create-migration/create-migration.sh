#!/usr/bin/env bash
# create-migration.sh - Generate Alembic migration with project conventions

set -euo pipefail

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

PROJECT_ROOT="/c/laragon/www/agenteWhatsapp"
cd "$PROJECT_ROOT"

# Check argument
if [ $# -eq 0 ]; then
    echo -e "${RED}Usage: $0 \"descripcion-del-cambio\"${NC}"
    echo "Example: $0 \"add-auto-confirm-to-restaurants\""
    exit 1
fi

MIGRATION_NAME="$1"

# Validate name format (kebab-case)
if [[ ! "$MIGRATION_NAME" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]]; then
    echo -e "${RED}Error: Migration name must be kebab-case (lowercase, hyphens only)${NC}"
    echo "Example: add-auto-confirm-to-restaurants"
    exit 1
fi

echo -e "${GREEN}Generating migration: $MIGRATION_NAME${NC}"

# Activate venv and run alembic
source .venv/Scripts/activate

echo -e "${YELLOW}Running: alembic revision --autogenerate -m \"$MIGRATION_NAME\"${NC}"
alembic revision --autogenerate -m "$MIGRATION_NAME"

# Find the generated file
LATEST_MIGRATION=$(ls -t alembic/versions/*.py | head -1)
echo -e "${GREEN}Generated: $LATEST_MIGRATION${NC}"

echo -e "${YELLOW}Validation checklist:${NC}"
echo "1. Check enums have native_enum=False"
echo "2. Check CHECK constraints are explicit in __table_args__"
echo "3. Run: alembic upgrade head"
echo "4. Verify with: alembic check"

echo ""
echo -e "${YELLOW}Do you want to apply the migration now? (y/N)${NC}"
read -r APPLY

if [[ "$APPLY" =~ ^[Yy]$ ]]; then
    echo -e "${GREEN}Applying migration...${NC}"
    alembic upgrade head
    echo -e "${GREEN}Verifying...${NC}"
    alembic check
    echo -e "${GREEN}Done!${NC}"
else
    echo "Migration generated but not applied. Run 'alembic upgrade head' when ready."
fi