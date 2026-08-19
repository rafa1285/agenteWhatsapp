---
name: create-migration
description: Generate and validate Alembic migrations with project conventions (native_enum=False, explicit CHECK constraints, UUID gen_random_uuid)
disable-model-invocation: true
---

# Create Migration Skill

Generates a new Alembic migration following project conventions and validates it.

## Conventions to Follow

1. **Enums**: Use `native_enum=False` with explicit `CHECK` constraints in `__table_args__`
2. **UUIDs**: Primary keys use `gen_random_uuid()` (PostgreSQL 13+)
3. **Naming**: Descriptive message in kebab-case (e.g., `add-auto-confirm-to-restaurants`)
4. **Validation**: After generation, verify CHECK constraints render correctly

## Usage

```bash
# From project root
.claude/skills/create-migration/create-migration.sh "descripcion-del-cambio"
```

## Validation Checklist

After `alembic revision --autogenerate -m "..."`:

- [ ] Check `versions/*.py` - enums have `native_enum=False`
- [ ] Check `CHECK` constraints are explicit in `__table_args__`
- [ ] Run `alembic upgrade head` to apply
- [ ] Verify with `alembic check` (no pending changes)