.PHONY: help setup test test-fast node deploy demo verify clean prewarm

PY := .venv/bin/python
PROBE ?= probe.jpg
QUERY ?= \#portrait

help:
	@echo "faceanchor - HH Goa 2026 Task 3"
	@echo
	@echo "  make setup     create the venv and install everything"
	@echo "  make prewarm   download the face model now, not during a demo"
	@echo "  make test      full suite (loads the real model)"
	@echo "  make test-fast fast suite, no model load"
	@echo "  make node      persistent local chain on 127.0.0.1:8545 (separate terminal)"
	@echo "  make deploy    deploy EvidenceRegistry, print CONTRACT_ADDRESS"
	@echo "  make demo      run the pipeline    PROBE=probe.jpg QUERY='#tag'"
	@echo "  make verify    verify the newest run"
	@echo "  make clean     remove runs/ and caches"

setup:
	uv venv --python 3.12 .venv
	uv pip install --python $(PY) insightface onnxruntime opencv-python-headless numpy \
		"web3[tester]" eth-account py-solc-x httpx typer rich beautifulsoup4 pytest
	@echo "\nNow: cp .env.example .env"

# The first run downloads ~281 MB of model weights. Doing that live on camera
# is the most avoidable way to ruin a recording.
prewarm:
	$(PY) -c "from src.face.encoder import FaceEncoder; FaceEncoder(); print('face model ready')"
	$(PY) -c "from src.chain.registry import compile_contract; compile_contract(); print('solc ready, contract compiles')"

test:
	$(PY) -m pytest tests/

test-fast:
	$(PY) -m pytest tests/ -m "not slow"

node:
	npx hardhat node --port 8545

deploy:
	$(PY) -m src.cli deploy

# `run` exits 1 when it finds no match. That is a real outcome, not a failure -
# the pipeline ran, produced a full evidence bundle and anchored it - so it is
# reported rather than turned into "make: *** Error 1". Exit codes above 1 are
# genuine errors and still stop the build.
demo:
	@$(PY) -m src.cli run --image "$(PROBE)" --query "$(QUERY)"; \
	code=$$?; \
	if [ $$code -eq 1 ]; then \
		echo "\n  (no match - the run completed and the evidence is anchored)"; \
	elif [ $$code -ne 0 ]; then \
		exit $$code; \
	fi

verify:
	@RUN=$$(ls -dt runs/*/ 2>/dev/null | head -1); \
	if [ -z "$$RUN" ]; then echo "no runs yet - try: make demo"; exit 1; fi; \
	$(PY) -m src.cli verify --run "$${RUN%/}"

clean:
	rm -rf runs .cache .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
