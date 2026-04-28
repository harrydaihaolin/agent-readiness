.PHONY: install dev test lint clean build release

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

lint:
	ruff check src tests

clean:
	rm -rf build dist *.egg-info src/*.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +

build: clean
	python -m build

release: build
	@echo "Artifacts in dist/:"
	@ls -lh dist/
	@echo ""
	@echo "Next: git tag v$$(python -c 'import agent_readiness; print(agent_readiness.__version__)') && git push origin --tags"
