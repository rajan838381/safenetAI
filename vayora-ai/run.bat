@echo off
REM One-click start for Windows
cd /d %~dp0
if not exist .venv ( py -m venv .venv )
call .venv\Scripts\activate
pip install -q -r requirements.txt
if not exist .env copy .env.example .env
start http://localhost:8000
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
