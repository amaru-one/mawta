---
name: format
description: Format code with Prettier to maintain consistent style
---

Format all code to match project style using Prettier.

## Steps

1. **Run Prettier**: Execute `npx prettier --write .` to format all files
2. **Report**: Show which files were reformatted, or report "Already formatted" if no changes

Use this before committing to ensure consistent formatting, or when reviewing code style issues.

## Command reference

```bash
npx prettier --write .              # Format all files
npx prettier --check .              # Check formatting without writing
npx prettier --write <filename>     # Format a specific file
```
