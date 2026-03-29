
import os
from pathlib import Path

# Configuration
PROJECT_ROOT = Path(r"C:\Users\jk023\Desktop\project-nia")
OUTPUT_DIR = Path(r"C:\Users\jk023\.gemini\antigravity\brain\d6f7ce6c-4ae0-4f0e-91e8-4b5f900355ab")
OUTPUT_FILE = OUTPUT_DIR / "source_code_bundle.md"

# Target Files (Relative to PROJECT_ROOT)
TARGET_FILES = [
    "backend/server.py",
    "backend/core/config.py",
    "backend/core/agent.py",
    "backend/core/tech_manual.md",
    "backend/services/memory_manager.py",
    "backend/services/memory_judge.py",
    "backend/services/speech_sanitizer.py",
    "backend/controllers/api/stream_router.py",
    "frontend/app/page.tsx",
    "frontend/components/AvatarView.tsx",
    "frontend/lib/api.ts",
]

def generate_bundle():
    print(f"Generating bundle at {OUTPUT_FILE}...")
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as out_f:
        # Header
        out_f.write("# Project Nia: Source Code Bundle\n\n")
        out_f.write("主要機能に関連するコアファイルのソースコードまとめです。\n\n")
        
        # Table of Contents
        out_f.write("## 収録ファイル一覧\n")
        for rel_path in TARGET_FILES:
            out_f.write(f"- `{rel_path}`\n")
        out_f.write("\n---\n\n")
        
        # File Contents
        for rel_path in TARGET_FILES:
            full_path = PROJECT_ROOT / rel_path
            
            out_f.write(f"## File: `{rel_path}`\n\n")
            
            if not full_path.exists():
                out_f.write("> [!WARNING]\n> File not found.\n\n")
                continue
                
            # Detect language for syntax highlighting
            ext = full_path.suffix.lower()
            lang = "text"
            if ext == ".py": lang = "python"
            elif ext in [".ts", ".tsx"]: lang = "typescript"
            elif ext == ".md": lang = "markdown"
            elif ext == ".json": lang = "json"
            
            try:
                content = full_path.read_text(encoding="utf-8")
                out_f.write(f"```{lang}\n")
                out_f.write(content)
                out_f.write("\n```\n\n")
            except Exception as e:
                out_f.write(f"> [!CAUTION]\n> Failed to read file: {e}\n\n")
            
            out_f.write("---\n\n")
            
    print("Bundle generation complete.")

if __name__ == "__main__":
    generate_bundle()
