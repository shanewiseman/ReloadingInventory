#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

.venv/bin/python -m pytest

{
  cat <<'HEADER'
# Coverage Report

Refresh this report after changing application code or tests:

```bash
scripts/update_coverage_report.sh
```

HEADER
  .venv/bin/python -m coverage report --format=markdown
} > docs/coverage.md
