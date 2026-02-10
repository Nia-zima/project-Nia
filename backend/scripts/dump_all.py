from datetime import datetime
from pathlib import Path

from backend.core.config import settings

PROJECT_ROOT = settings.PROJECT_ROOT
BASE_OUTPUT_NAME = PROJECT_ROOT / "project_dump"
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
    def __init__(self, base_name: Path, max_size: int):
        self.base_name = base_name
        self.max_size = max_size
        self.part = 1
        self.current_file = None
        self.current_filename = None
        self._open_next()

    def _open_next(self) -> None:
        if self.current_file:
            self.current_file.close()
        
        filename = f"{self.base_name.name}_{self.part:02d}.txt"
        self.current_filename = self.base_name.parent / filename
        self.current_file = self.current_filename.open("w", encoding="utf-8")
        print(f"--> Creating new dump file: {self.current_filename}")
        
        header = f"Project Dump Part {self.part} generated at {datetime.now().isoformat()}\n\n"
        self.current_file.write(header)
        self.part += 1

    def write(self, data: str) -> None:
        # 概算サイズチェック（厳密でなくて良い）
        if self.current_file.tell() + len(data) > self.max_size:
            self._open_next()
        self.current_file.write(data)

    def close(self) -> None:
        if self.current_file:
            self.current_file.close()

def dump_files() -> None:
    print(f"Starting dump from: {PROJECT_ROOT}")
    writer = RollingFileWriter(BASE_OUTPUT_NAME, MAX_FILE_SIZE)

    try:
        for full_path in PROJECT_ROOT.rglob("*"):
            if full_path.is_dir():
                continue
            rel_path = full_path.relative_to(PROJECT_ROOT)
            if any(d in rel_path.parts for d in IGNORE_DIRS):
                continue
            if rel_path.name in IGNORE_FILES:
                continue
            if rel_path.name.startswith("."):
                continue
            if rel_path.name.startswith("project_dump_"):
                continue

            ext = rel_path.suffix.lower()
            if ext in IGNORE_EXTS:
                continue

                try:
                    with full_path.open("r", encoding="utf-8", errors="ignore") as infile:
                        content = infile.read()
                        # Remove unusual line terminators
                        content = content.replace("\u2028", "\n").replace("\u2029", "\n")

                        out_chunk = (
                            "=" * 50
                            + f"\nFILE: {rel_path}\n"
                            + "=" * 50
                            + "\n"
                            + content
                            + "\n\n"
                        )
                        writer.write(out_chunk)

                except Exception as e:
                    print(f"Skipped {rel_path}: {e}")

    finally:
        writer.close()
        print("Done.")

if __name__ == "__main__":
    dump_files()
