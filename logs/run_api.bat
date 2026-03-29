@echo off
cd /d "C:\Users\jk023\Desktop\project-nia"
set "PYTHONPATH=C:\Users\jk023\Desktop\project-nia"
"C:\Users\jk023\Desktop\project-nia\.venv\Scripts\python.exe" -m uvicorn backend.server:app --host 0.0.0.0 --port 8000 --reload >> "C:\Users\jk023\Desktop\project-nia\logs\api_20260108_011617.log" 2>&1
