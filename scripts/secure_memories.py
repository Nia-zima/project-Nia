import shutil
from pathlib import Path

def safe_copy(src: Path, dst_folder: Path) -> None:
    if src.exists():
        file_name = src.name
        dst = dst_folder / file_name
        try:
            shutil.copy2(src, dst)
            print(f"✅ Secured: {file_name}")
        except Exception as e:
            print(f"❌ Failed to secure {file_name}: {e}")
    else:
        print(f"⚠️ Not found (skip): {src}")

def secure_memories() -> None:
    # Go up one level from 'scripts' to project root
    project_root = Path(__file__).resolve().parents[1]
    dest_dir = project_root / "saved_memories_critical"

    dest_dir.mkdir(parents=True, exist_ok=True)
    
    # List of critical memory files
    critical_files = [
        "backend/memories.db",
        "backend/evolution.txt",
        "chat_history.db",
        "user_profile.json",
        "backend/chroma_db",  # Valid directory
        "faiss_index",        # Valid directory
    ]
    
    print("--- Starting Critical Memory Preservation ---")
    for item in critical_files:
        path = project_root / item
        if path.is_dir():
            dst = dest_dir / Path(item).name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(path, dst)
            print(f"✅ Secured Directory: {item}")
        else:
            safe_copy(path, dest_dir)
            
    print("--- Memory Preservation Completed ---")

if __name__ == "__main__":
    secure_memories()
