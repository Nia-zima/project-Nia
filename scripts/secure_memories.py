import shutil
import os
import time

def safe_copy(src, dst_folder):
    if os.path.exists(src):
        file_name = os.path.basename(src)
        dst = os.path.join(dst_folder, file_name)
        try:
            shutil.copy2(src, dst)
            print(f"✅ Secured: {file_name}")
        except Exception as e:
            print(f"❌ Failed to secure {file_name}: {e}")
    else:
        print(f"⚠️ Not found (skip): {src}")

def secure_memories():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # Go up one level from 'scripts' to project root
    project_root = os.path.dirname(base_dir)
    dest_dir = os.path.join(project_root, "saved_memories_critical")
    
    os.makedirs(dest_dir, exist_ok=True)
    
    # List of critical memory files
    critical_files = [
        "backend/memories.db",
        "backend/evolution.txt",
        "chat_history.db",
        "user_profile.json",
        "backend/chroma_db", # Valid directory
        "faiss_index"        # Valid directory
    ]
    
    print("--- Starting Critical Memory Preservation ---")
    for item in critical_files:
        path = os.path.join(project_root, item)
        if os.path.isdir(path):
            dst = os.path.join(dest_dir, os.path.basename(item))
            if os.path.exists(dst): shutil.rmtree(dst)
            shutil.copytree(path, dst)
            print(f"✅ Secured Directory: {item}")
        else:
            safe_copy(path, dest_dir)
            
    print("--- Memory Preservation Completed ---")

if __name__ == "__main__":
    secure_memories()
