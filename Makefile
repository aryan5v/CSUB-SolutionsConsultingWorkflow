PYTHON ?= python3
VENV ?= .venv
PRE_COMMIT ?= $(VENV)/bin/pre-commit

REVIEW_AGENT ?= services/review-agent
REVIEWER_WEB ?= apps/reviewer-web
INFRA ?= infra

.PHONY: bootstrap hooks check lint test verify review-agent reviewer-web infra-check agent-briefs aws-whoami

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
	@$(PYTHON) -m compileall -q scripts tests $(REVIEW_AGENT)/src $(REVIEW_AGENT)/tests

test:
	@$(PYTHON) -m unittest discover -s tests -p 'test_*.py'

# Deterministic, stdlib-only review-agent slice. No live AWS; joins the gate.
review-agent:
	@$(MAKE) -C $(REVIEW_AGENT) test

# Locked React/Vite workspace: install, unit-test API seams, type-check, and build.
reviewer-web:
	@npm --prefix $(REVIEWER_WEB) ci
	@npm --prefix $(REVIEWER_WEB) run test
	@npm --prefix $(REVIEWER_WEB) run check
	@npm --prefix $(REVIEWER_WEB) run build

# Non-mutating CDK checks only. Deployment still requires the documented gate.
infra-check:
	@npm --prefix $(INFRA) ci
	@npm --prefix $(INFRA) run typecheck
	@npm --prefix $(INFRA) test
	@npm --prefix $(INFRA) run synth -- --strict

verify: check lint test review-agent reviewer-web infra-check
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
