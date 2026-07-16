# demo-agent — Python 3.11+ required (set PYTHON to a 3.11+ interpreter if `python3` is older)
PYTHON ?= python3
PY = .venv/bin/python
PIP = .venv/bin/pip

.PHONY: setup local-setup run report reset-auth clean
setup:  ## create venv, install deps, install Chromium, scaffold .env
	@$(PYTHON) -c 'import sys; sys.version_info >= (3, 11) or sys.exit("ERROR: Python 3.11+ required, found %d.%d — rerun as: make setup PYTHON=/path/to/python3.11+" % sys.version_info[:2])'
	$(PYTHON) -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PY) -m playwright install chromium
	@test -f .env || cp .env.example .env
	@echo "Setup complete. Edit .env (add keys, or set PROVIDER_MODE=local), then: make run"

local-setup:  ## install local-model extras (Whisper + Kokoro); run Ollama separately
	$(PIP) install -r requirements-local.txt
	@echo "Local extras installed. Set PROVIDER_MODE=local in .env and start Ollama."

run:  ## launch the demo agent
	$(PY) -m src.app

report:  ## open the newest session's post-call report page
	$(PY) -m src.enrichment.view

reset-auth:  ## forget the saved app login (next run logs in fresh)
	rm -f .auth-state.json

clean:
	rm -rf .venv out/*.json **/__pycache__
