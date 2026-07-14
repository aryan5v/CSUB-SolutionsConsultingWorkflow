.PHONY: check aws-whoami

check:
	@python3 scripts/validate_repo.py

aws-whoami:
	aws sts get-caller-identity
