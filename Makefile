# Everything stays inside this folder: venv, uv cache, generated corpus, runs.
export UV_CACHE_DIR := $(CURDIR)/.uv-cache
export UV_PYTHON_DOWNLOADS := never
export UV_PYTHON := /usr/local/bin/python3.12
UV := uv
RUN := $(UV) run --frozen

.PHONY: sync check lint fmt types imports test corpus eval corrupt clean

sync:
	$(UV) sync

lint:
	$(RUN) ruff check src tests scripts
	$(RUN) ruff format --check src tests scripts

fmt:
	$(RUN) ruff format src tests scripts
	$(RUN) ruff check --fix src tests scripts

types:
	$(RUN) mypy

imports:
	$(RUN) lint-imports

test:
	$(RUN) pytest

guards:
	$(RUN) python scripts/check_inv_tests.py
	$(RUN) python scripts/check_no_float.py
	$(RUN) python scripts/check_no_pdfs.py
	$(RUN) python scripts/check_lockfile_registry.py

check: lint types imports guards test

corpus:
	$(RUN) statement forge --split dev --out corpus/dev
	$(RUN) statement forge --split unknown --out corpus/unknown
	$(RUN) statement forge --split drift --out corpus/drift

eval:
	$(RUN) statement eval corpus/dev --out runs
	$(RUN) statement eval corpus/unknown --out runs
	$(RUN) statement eval corpus/drift --out runs

corrupt:
	$(RUN) statement corrupt-eval corpus/dev --out runs

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache runs corpus
