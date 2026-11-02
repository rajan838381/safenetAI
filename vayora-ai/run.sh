#!/usr/bin/env bash
# One-click start for Mac / Linux
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env
echo "Open http://localhost:8000"
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
