# Workspace-local checks for the review agent. Composed into the root
# `make verify` gate via the root Makefile's `review-agent` target.
PYTHON ?= python3
SRC ?= src
TESTS ?= tests

.PHONY: lint typecheck test verify

# Byte-compile every module; catches syntax/import errors with no extra deps.
lint:
	@$(PYTHON) -m compileall -q $(SRC) $(TESTS)

# Optional strict tooling; only runs if the dev extra is installed.
typecheck:
	@command -v ruff >/dev/null 2>&1 && ruff check $(SRC) $(TESTS) || echo "ruff not installed; skipping (pip install -e '.[dev]')"
	@command -v mypy >/dev/null 2>&1 && mypy || echo "mypy not installed; skipping (pip install -e '.[dev]')"

# Deterministic, stdlib-only unit tests. No live AWS.
test:
	@PYTHONPATH=$(SRC) $(PYTHON) -m unittest discover -s $(TESTS) -p 'test_*.py'

verify: lint test
