#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
python check_setup.py
uvicorn app:app --host 127.0.0.1 --port 8787
