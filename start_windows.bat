@echo off
cd /d %~dp0
if not exist .venv py -m venv .venv
call .venv\Scripts\activate
python -m pip install -U pip
pip install -r requirements.txt
if not exist .env copy .env.example .env
python check_setup.py
uvicorn app:app --host 127.0.0.1 --port 8787
pause
