# Contributing to Purveyor

Thank you for your interest in contributing! This guide covers development setup, code style, testing requirements, and the PR process.

## Development Setup

```bash
# 1. Fork and clone
git clone https://github.com/your-username/skyfi-purveyor-mcp
cd skyfi-purveyor-mcp

# 2. Install dependencies (requires uv)
uv sync

# 3. Set up pre-commit (optional but recommended)
# Install ruff and mypy to run before committing

# 4. Verify everything works
uv run pytest -m "not live" -q
uv run mypy src/
uv run ruff check src/ tests/
```

## Code Style

- **Formatter**: `ruff format` (line length: 100)
- **Linter**: `ruff check` (E, F, W, I, N, UP, ANN, S, B, A, C4, PT, RUF)
- **Type checker**: `mypy --strict`
- **Python**: 3.11+ features are fine (StrEnum, match statements, etc.)
- **Imports**: `from __future__ import annotations` at top of every module

Run before committing:
```bash
uv run ruff format src/ tests/
uv run ruff check src/ tests/
uv run mypy src/
```

## Commit Conventions

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>
```

**Types**: `feat`, `fix`, `test`, `docs`, `refactor`, `chore`, `style`, `perf`

**Scopes**: `tools`, `core`, `models`, `webhooks`, `demo`, `deploy`, `docs`, `tests`

**Examples**:
```
feat(tools): add search_archives with pagination and caching
fix(core): handle expired Fernet tokens gracefully
test(tools): add hypothesis property tests for aoi validation
docs: update claude-web integration guide
chore(deploy): update Terraform AWS module for ECS
```

## Testing Requirements

- **New features** must include tests. No PR will be merged without tests for the new functionality.
- **Bug fixes** must include a regression test.
- **Coverage** must remain above 80% (`uv run pytest --cov=src/purveyor --cov-fail-under=80`).
- **Live API tests** are read-only operations only. Never create orders or notifications in automated tests.

```bash
# Run the full test suite
uv run pytest -m "not live" --cov=src/purveyor -q

# Run a specific test file
uv run pytest tests/test_archives_tool.py -v

# Run live tests (requires SKYFI_TEST_API_KEY)
SKYFI_TEST_API_KEY=your-key uv run pytest -m live -v
```

## Security Rules

- **Never store API keys** in the database or logs. The Fernet token IS the credential carrier.
- **Never log sensitive fields**: `api_key`, `delivery_params`, `aws_secret_key`, `gs_credentials`, `azure_connection_string`.
- **Webhooks are untrusted hints** — always verify against SkyFi API before updating state.
- **SkyFi API is source of truth** — Purveyor caches for performance, never contradicts SkyFi.

See `CLAUDE.md` and `.claude/rules/security.md` for full security guidelines.

## PR Process

1. **Fork** the repository and create a branch: `git checkout -b feat/your-feature`
2. **Make your changes** following the code style guidelines above
3. **Write tests** for your changes
4. **Run the full check suite**:
   ```bash
   uv run pytest -m "not live" -q
   uv run mypy src/
   uv run ruff check src/ tests/
   uv run ruff format --check src/ tests/
   ```
5. **Commit** with a conventional commit message
6. **Open a PR** against `main` with a clear description of the change and why

PRs that fail CI, have no tests, or violate security rules will not be merged.

## Architecture Notes

Before modifying these areas, read the referenced documentation:

| Area | Read first |
|------|-----------|
| Confirmation flow | `docs/DESIGN_DECISIONS.md` §1–§6 |
| Webhook handling | `docs/DESIGN_DECISIONS.md` §3–§4 |
| Error model | `docs/DESIGN_DECISIONS.md` §7 |
| Tool response format | `docs/DESIGN_DECISIONS.md` §14 |
| Demo agent | `docs/DESIGN_DECISIONS.md` §11 |

## Reporting Issues

Use the GitHub issue templates:
- **Bug report**: for unexpected behavior, errors, or crashes
- **Feature request**: for new tools, integrations, or capabilities

Please search existing issues before opening a new one.
