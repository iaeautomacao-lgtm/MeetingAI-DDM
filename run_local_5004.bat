@echo off
cd /d "%~dp0"
set PORT=5004
python -u local_server.py >> local-server-5004-live.log 2>&1
