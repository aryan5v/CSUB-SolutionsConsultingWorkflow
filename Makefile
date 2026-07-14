PYTHON ?= python3
VENV ?= .venv
PRE_COMMIT ?= $(VENV)/bin/pre-commit

.PHONY: bootstrap hooks check lint test verify agent-briefs aws-whoami

bootstrap:
	@$(PYTHON) -m venv $(VENV)
	@$(VENV)/bin/python -m pip install --upgrade pip
	@$(VENV)/bin/python -m pip install pre-commit==4.6.0
	@$(MAKE) hooks

hooks:
	@test -x $(PRE_COMMIT) || (echo "Run 'make bootstrap' first." && exit 1)
	@$(PRE_COMMIT) install --install-hooks --hook-type pre-commit --hook-type pre-push

check:
	@$(PYTHON) scripts/validate_repo.py
	@$(PYTHON) scripts/scan_secrets.py --all

lint:
	@$(PYTHON) -m compileall -q scripts tests

test:
	@$(PYTHON) -m unittest discover -s tests -p 'test_*.py'

verify: check lint test
	@git diff --check

agent-briefs:
	@command -v agentprop >/dev/null || (echo "Install AgentProp first." && exit 1)
	@mkdir -p artifacts/agentprop
	@agentprop analyze planner_coder_tester_reviewer --json > artifacts/agentprop/analysis.json
	@agentprop optimize planner_coder_tester_reviewer --budget 2 --algorithm greedy --model rzf --trials 50 --json > artifacts/agentprop/optimization.json
	@agentprop agent-instructions planner_coder_tester_reviewer --target codex --budget 2 --trials 50 --out artifacts/agentprop/codex_agent_brief.md
	@agentprop agent-instructions planner_coder_tester_reviewer --target claude-code --budget 2 --trials 50 --out artifacts/agentprop/claude_code_agent_brief.md
	@agentprop report planner_coder_tester_reviewer --budget 2 --algorithm greedy --model rzf --trials 50 --out artifacts/agentprop/report.html --format html
	@echo "AgentProp artifacts written to artifacts/agentprop/."

aws-whoami:
	aws sts get-caller-identity
