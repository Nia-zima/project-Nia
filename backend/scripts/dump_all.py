import os

PROJECT_ROOT = r"C:\Users\jk023\Desktop\AI_Buddy"
BASE_OUTPUT_NAME = os.path.join(PROJECT_ROOT, "project_dump")
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2MB per file

# 除外リスト (ノイズになるもの)
IGNORE_DIRS = {
    ".git", ".venv", "node_modules", ".next", "__pycache__", 
    "logs", "chroma_db", "obs_output", "sleep_outputs", "docs", "tmp", "venv", ".idea", ".vscode",
    "saved_memories_critical", "faiss_index", "identity_snapshots", "backups"
}
IGNORE_FILES = {
    "project_dump.txt", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", 
    "dump_all.py", ".DS_Store", "README.txt", "chat_history.db"
}
IGNORE_EXTS = {
    ".pyc", ".png", ".jpg", ".jpeg", ".ico", ".jsonl", ".sqlite3", 
    ".pkl", ".bin", ".exe", ".dll", ".so", ".dylib", ".mp3", ".wav",
    ".db", ".zip", ".log", ".gz", ".tar"
}

class RollingFileWriter:
    def __init__(self, base_name, max_size):
        self.base_name = base_name
        self.max_size = max_size
        self.part = 1
        self.current_file = None
        self.current_filename = None
        self._open_next()

    def _open_next(self):
        if self.current_file:
            self.current_file.close()
        
        self.current_filename = f"{self.base_name}_{self.part:02d}.txt"
        self.current_file = open(self.current_filename, "w", encoding="utf-8")
        print(f"--> Creating new dump file: {self.current_filename}")
        
        header = f"Project Dump Part {self.part} generated at {os.environ.get('TIME', 'Unknown')}\n\n"
        self.current_file.write(header)
        self.part += 1

    def write(self, data):
        # 概算サイズチェック（厳密でなくて良い）
        if self.current_file.tell() + len(data) > self.max_size:
            self._open_next()
        self.current_file.write(data)

    def close(self):
        if self.current_file:
            self.current_file.close()

def dump_files():
    print(f"Starting dump from: {PROJECT_ROOT}")
    writer = RollingFileWriter(BASE_OUTPUT_NAME, MAX_FILE_SIZE)

    try:
        for root, dirs, files in os.walk(PROJECT_ROOT):
            # 除外ディレクトリを探索対象から外す
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            
            for f in files:
                if f in IGNORE_FILES: continue
                if f.startswith("."): continue 
                
                ext = os.path.splitext(f)[1].lower()
                if ext in IGNORE_EXTS: continue
                
                # 分割ファイル自体を除外
                if f.startswith("project_dump_"): continue

                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, PROJECT_ROOT)

                # Skip if file path contains ignored dirs (safety catch)
                if any(d in rel_path.split(os.sep) for d in IGNORE_DIRS):
                    continue

                try:
                    with open(full_path, "r", encoding="utf-8", errors='ignore') as infile:
                        content = infile.read()
                        # Remove unusual line terminators
                        content = content.replace('\u2028', '\n').replace('\u2029', '\n')
                        
                        out_chunk = ""
                        out_chunk += "=" * 50 + "\n"
                        out_chunk += f"FILE: {rel_path}\n"
                        out_chunk += "=" * 50 + "\n"
                        out_chunk += content + "\n\n"
                        
                        writer.write(out_chunk)
                        # print(f"Added: {rel_path}")
                        
                except Exception as e:
                    print(f"Skipped {rel_path}: {e}")

    finally:
        writer.close()
        print("Done.")

if __name__ == "__main__":
    dump_files()
