import zipfile
from pathlib import Path
from datetime import datetime

def backup_project() -> None:
    # project_root is assumed to be one level up from this script (scripts/)
    project_root = Path(__file__).resolve().parents[1]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = project_root / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    backup_filename = f"AI_Buddy_Backup_{timestamp}.zip"
    backup_path = backup_dir / backup_filename

    exclude_dirs = {".venv", "__pycache__", ".git", "node_modules", "backups", ".vscode", ".idea"}
    exclude_exts = {".zip", ".log"}
    exclude_files = {"chat_history.db"}

    print("Starting backup...")
    print(f"Source: {project_root}")
    print(f"Destination: {backup_path}")

    try:
        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path in project_root.rglob("*"):
                if file_path.is_dir():
                    continue
                rel_path = file_path.relative_to(project_root)
                if any(part in exclude_dirs for part in rel_path.parts):
                    continue
                if file_path.name in exclude_files or file_path.suffix.lower() in exclude_exts:
                    continue

                try:
                    zipf.write(file_path, rel_path)
                except PermissionError:
                    print(f"Skipped (Permission Denied): {rel_path}")
                except OSError as e:
                    print(f"Skipped (Error): {rel_path} - {e}")

        print(f"Backup completed successfully: {backup_filename}")

    except Exception as e:
        print(f"Backup failed: {e}")

if __name__ == "__main__":
    backup_project()
