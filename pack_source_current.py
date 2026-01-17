import os
from pathlib import Path

# Config
OUTPUT_FILE = "NIA_FULL_SOURCE_CURRENT_20260115.txt"
ROOT_DIR = Path(os.getcwd())

INCLUDED_EXTENSIONS = {".py", ".bat", ".md", ".json"}
EXCLUDED_DIRS = {
    "__pycache__", ".git", ".venv", "node_modules", 
    "_ARCHIVE", "logs", "data", "frontend", "backend_legacy",
    "tests" # Tests seem to be old or not main focus, exclude if not critical
}

# Root files to explicitly include (even if directory is excluded or logic skips)
EXPLICIT_ROOT_FILES = [
    "LAUNCH_NIA_COMPLETE.bat",
    "identity.md",
    "Nia_Identity_Card.md",
    "project_structure.md",
    "user_profile.json",
    "public_status.json"
]

def is_excluded(path: Path) -> bool:
    # Check parts
    for part in path.parts:
        if part in EXCLUDED_DIRS:
            return True
    return False

def pack():
    print(f"Packing source code from {ROOT_DIR} to {OUTPUT_FILE}...")
    
    files_to_pack = []
    
    # 1. Walk through backend
    backend_dir = ROOT_DIR / "backend"
    if backend_dir.exists():
        for root, dirs, files in os.walk(backend_dir):
            # Edit dirs in-place to skip excluded
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
            
            for file in files:
                file_path = Path(root) / file
                if file_path.suffix in INCLUDED_EXTENSIONS:
                    # Double check exclusion
                    if not is_excluded(file_path.relative_to(ROOT_DIR)):
                        files_to_pack.append(file_path)

    # 2. Add explicit root files
    for fname in EXPLICIT_ROOT_FILES:
        fpath = ROOT_DIR / fname
        if fpath.exists():
            if fpath not in files_to_pack:
                files_to_pack.append(fpath)

    # Sort files for consistency
    files_to_pack.sort()
    
    print(f"Found {len(files_to_pack)} files.")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        for fpath in files_to_pack:
            try:
                rel_path = fpath.relative_to(ROOT_DIR)
                print(f"Processing: {rel_path}")
                
                content = fpath.read_text(encoding="utf-8", errors="ignore")
                
                out.write(f"\n\n========== {rel_path} ==========\n")
                out.write(content)
                out.write("\n")
            except Exception as e:
                print(f"Error reading {fpath}: {e}")
                
    print("Done.")
    print(f"Created: {os.path.abspath(OUTPUT_FILE)}")

if __name__ == "__main__":
    pack()
