.PHONY: install dev test lint clean build release dashboard scan-and-view-dev dashboard-fixtures

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

test:
	PYTHONPATH=src python3 -m pytest tests -v

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

dashboard:
	cd ../agent-readiness-analytics-dashboard && npm ci && npm run build
	rm -rf src/agent_readiness/_dashboard_dist
	cp -R ../agent-readiness-analytics-dashboard/dist src/agent_readiness/_dashboard_dist
	python3 scripts/check_dashboard_dist.py

scan-and-view-dev:
	PYTHONPATH=src python3 -m agent_readiness.cli scan-and-view . --children .

dashboard-fixtures:
	PYTHONPATH=src python3 -m agent_readiness.cli scan-and-view . --children . --no-open &
	sleep 8
	cp -R $$HOME/.agent-readiness/scans/* ../agent-readiness-analytics-dashboard/public/data/scans/ || true
