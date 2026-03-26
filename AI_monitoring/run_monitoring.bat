@echo off
cd /d C:\AI_monitoring
pip install -q google-genai>=1.0.0
python production_monitoring.py --force
pause
