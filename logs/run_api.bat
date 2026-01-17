@echo off
cd /d "C:\Users\jk023\Desktop\AI_Buddy"
set "PYTHONPATH=C:\Users\jk023\Desktop\AI_Buddy"
"C:\Users\jk023\Desktop\AI_Buddy\.venv\Scripts\python.exe" -m uvicorn backend.server:app --host 0.0.0.0 --port 8000 --reload >> "C:\Users\jk023\Desktop\AI_Buddy\logs\api_20260108_011617.log" 2>&1
