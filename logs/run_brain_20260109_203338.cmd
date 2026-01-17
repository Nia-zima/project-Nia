@echo off
cd /d "C:\Users\jk023\Desktop\AI_Buddy"
set "PYTHONPATH=C:\Users\jk023\Desktop\AI_Buddy"
"C:\Users\jk023\Desktop\AI_Buddy\.venv\Scripts\python.exe" -m backend.core.agent >> "C:\Users\jk023\Desktop\AI_Buddy\logs\brain_20260109_203338.log" 2>&1
