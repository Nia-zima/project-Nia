@echo off
cd /d "C:\Users\jk023\Desktop\AI_Buddy"
set "PYTHONPATH=C:\Users\jk023\Desktop\AI_Buddy"
"C:\Users\jk023\Desktop\AI_Buddy\.venv\Scripts\python.exe" -m backend.scripts.obs_writer >> "C:\Users\jk023\Desktop\AI_Buddy\logs\obs_20260108_011617.log" 2>&1
