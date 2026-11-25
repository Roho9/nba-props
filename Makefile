# NBA prop research dashboard. Run from the repo root.
PY := backend/.venv/bin/python
PY_SYS ?= python3.13

.PHONY: setup backend frontend test backfill refresh backtest summary clean-data

setup:      ## create the Python venv and install both apps
	$(PY_SYS) -m venv backend/.venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r backend/requirements.txt
	cd frontend && npm install --no-audit --no-fund
	test -f backend/.env || cp .env.example backend/.env

backend:    ## FastAPI on :8000 (auto-refreshes every AUTO_REFRESH_MIN)
	cd backend && .venv/bin/uvicorn app.api.main:app --host 127.0.0.1 --port 8000

frontend:   ## Next.js on :3000
	cd frontend && npm run dev

test:       ## unit tests (offline, synthetic fixture DB)
	cd backend && .venv/bin/python -m pytest

backfill:   ## schedules + box scores for both seasons + this season's prop boards (~30 min cold, resumable)
	cd backend && .venv/bin/python -u -c "from app.ingest import backfill; backfill()"

refresh:    ## run today's pipeline once from the command line
	cd backend && .venv/bin/python -u -c "from app import pipeline; r = pipeline.evaluate(pipeline.today_slate()); print(r['overview']['headline'] or 'qualifying picks published')"

backtest:   ## walk-forward validation; writes backend/data/validation_report.json
	cd backend && .venv/bin/python -u -m app.backtest.run

summary:
	cd backend && .venv/bin/python -c "import json; r=json.load(open('data/validation_report.json')); print(r['status']); print('\n'.join(r['betting_validation'].get('reasons', [])))"

clean-data: ## delete the local database (this also deletes the prediction history)
	rm -rf backend/data/*.sqlite3* backend/data/*.json backend/data/*.csv
