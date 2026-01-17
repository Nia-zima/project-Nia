import shutil
import os
import datetime
import zipfile

def backup_project():
    # project_root is assumed to be one level up from this script (scripts/)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(project_root, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    
    backup_filename = f"AI_Buddy_Backup_{timestamp}.zip"
    backup_path = os.path.join(backup_dir, backup_filename)
    
    print(f"Starting backup...")
    print(f"Source: {project_root}")
    print(f"Destination: {backup_path}")
    
    try:
        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(project_root):
                # Exclude directories
                # modify dirs in-place to prune the walk
                dirs[:] = [d for d in dirs if d not in ['.venv', '__pycache__', '.git', 'node_modules', 'backups', '.vscode', '.idea']]
                
                for file in files:
                    # Exclude large binaries or previous backups if any leak in (though backups dir is excluded)
                    if file.endswith('.zip') or file.endswith('.log') or file == "chat_history.db":
                        # chat_history.db is 174MB, maybe skip for light backup unless requested?
                        # User said "Backup save", usually implies all state. 
                        # But it might be locked if server is running.
                        # I will try to include it, but catch permission errors.
                        # Actually, server is running, so DBs might be locked.
                        pass
                        
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, project_root)
                    
                    try:
                        zipf.write(file_path, arcname)
                    except PermissionError:
                        print(f"Skipped (Permission Denied): {arcname}")
                    except OSError as e:
                        print(f"Skipped (Error): {arcname} - {e}")
                        
        print(f"Backup completed successfully: {backup_filename}")
        
    except Exception as e:
        print(f"Backup failed: {e}")

if __name__ == "__main__":
    backup_project()
