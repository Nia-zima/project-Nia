@echo off
cd /d "C:\Users\jk023\Desktop\project-nia"
set "PYTHONPATH=C:\Users\jk023\Desktop\project-nia"
"C:\Users\jk023\Desktop\project-nia\.venv\Scripts\python.exe" -m backend.core.agent >> "C:\Users\jk023\Desktop\project-nia\logs\brain_20260108_011617.log" 2>&1
