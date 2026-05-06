PYTHON ?= python

.PHONY: run-mcp smoke smoke-container validate test

run-mcp:
	./scripts/run-local.sh

smoke:
	./scripts/smoke-mcp.sh

smoke-container:
	./scripts/smoke-container.sh

test:
	$(PYTHON) -m unittest discover -s tests -v

validate:
	./scripts/validate-local.sh
