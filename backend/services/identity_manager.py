from datetime import datetime

from backend.core.logger import logger

from backend.core.config import settings

class IdentityManager:
    def __init__(self) -> None:
        self.project_root = settings.PROJECT_ROOT
        self.file_path = self.project_root / "identity.md"
        self.snapshot_dir = self.project_root / "identity_snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self._identity_cache = ""
        # 認証キー
        self._secret_key = "INTERNAL_SLEEP_PROCESS_ONLY"

    def load_identity(self) -> str:
        """identity.md を読み込む"""
        if not self.file_path.exists():
            return "# Near (ニア)\n\nあなたは親切なAIアシスタントです。"
        try:
            with self.file_path.open("r", encoding="utf-8") as f:
                self._identity_cache = f.read().strip()
            return self._identity_cache
        except Exception as e:
            logger.error(f"Error loading identity: {e}")
            return ""

    def get_identity(self) -> str:
        return self.load_identity()

    def _save_snapshot(self, content: str, label: str) -> None:
        """
        スナップショット保存
        Format: YYYY-MM-DD_HHMMSS_label.md
        """
        try:
            # 時刻を含めてユニークにする
            ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            filename = f"{ts}_{label}.md"
            path = self.snapshot_dir / filename
            
            with path.open("w", encoding="utf-8") as f:
                f.write(content)
            # logger.info(f"📸 Snapshot saved: {filename}")
        except Exception as e:
            logger.error(f"Snapshot failed: {e}")

    def update_identity(self, new_content: str, key: str | None = None) -> bool:
        """
        権限分離書き込み & スナップショット作成
        """
        # 1. 権限チェック
        if key != self._secret_key:
            logger.error("⛔ Unauthorized identity update attempt (Invalid Key)")
            return False

        try:
            if not new_content:
                return False

            # 2. Before Snapshot
            current_content = self.load_identity()
            self._save_snapshot(current_content, "before")

            # 3. Write
            with self.file_path.open("w", encoding="utf-8") as f:
                f.write(new_content)
            self._identity_cache = new_content

            # 4. After Snapshot
            self._save_snapshot(new_content, "after")
            
            logger.info("✅ Identity Updated (Authorized & Snapshot Saved).") 
            return True
            
        except Exception as e:
            logger.error(f"❌ Identity Update Error: {e}")
            return False

identity_manager = IdentityManager()
