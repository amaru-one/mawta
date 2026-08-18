---
name: verify
description: Run linting and type checks before committing to catch issues early
---

Run comprehensive checks to ensure code quality and correctness before committing.

## Steps

1. **Type check**: Run `bun run check` to verify TypeScript compilation and Svelte types
2. **Lint code**: Run ESLint on all changed files
3. **Report results**: Show any errors and suggest fixes

If all checks pass, report "All clear — ready to commit."

If checks fail, stop and explain what needs fixing. Suggest fixes for linting errors when possible (import order, formatting issues, etc.).

## Command reference

```bash
bun run check       # TypeScript + svelte-check
bun eslint .        # Lint all files (or specify files to lint only changed ones)
```
