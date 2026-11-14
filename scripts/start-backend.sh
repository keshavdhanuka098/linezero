#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/../backend"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt
python -m app.core.init_db
[ -f data/seeded.flag ] || { python -m app.seed.generate_demo_data --scenario all --customers 500 --seed 42 --reset && touch data/seeded.flag; }
uvicorn app.main:app --host 127.0.0.1 --port 8000
