.PHONY: check aws-whoami

check:
	@test -f README.md
	@test -f AGENTS.md
	@test -f CLAUDE.md
	@test -f docs/PRD.md
	@test -f infra/README.md
	@echo "Project shell checks passed."

aws-whoami:
	aws sts get-caller-identity
