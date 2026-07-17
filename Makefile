# demo-agent — reproducible installs via uv: the SAME pinned CPython (3.12) is
# provisioned on every machine, regardless of what the system has. If uv itself
# is missing, `make setup` installs it (announced, to ~/.local/bin).
PYTHON_VERSION := 3.12
UV := $(shell command -v uv 2>/dev/null || echo $(HOME)/.local/bin/uv)
PY = .venv/bin/python

.PHONY: setup run report reset-auth clean

setup:  ## provision pinned Python + venv + deps + Chromium, scaffold .env
	@command -v uv >/dev/null 2>&1 || test -x $(UV) || { \
	  echo "uv not found — installing it to ~/.local/bin (astral.sh installer)"; \
	  curl -LsSf https://astral.sh/uv/install.sh | sh; }
	$(UV) venv .venv --python $(PYTHON_VERSION)
	$(UV) pip install --python $(PY) -r requirements.txt
	$(PY) -m playwright install chromium
	@test -f .env || cp .env.example .env
	@echo "Setup complete. Run: make run  (keys are collected on first run, or edit .env)"

run:  ## launch the demo agent
	$(PY) -m src.app

report:  ## open the newest session's post-call report page
	$(PY) -m src.enrichment.view

reset-auth:  ## forget the saved app login (next run logs in fresh)
	rm -f .auth-state.json

clean:
	rm -rf .venv out/*.json **/__pycache__
