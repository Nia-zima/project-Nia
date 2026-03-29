"""
Migration script for Pip Scraps (Phase B).
Creates the `pip_scraps` table in the database.
"""

import sys
from pathlib import Path

# Add project root to sys.path so we can import backend
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from backend.core.db import managed_conn
from backend.core.config import settings
from backend.core.logger import logger


def run_migration():
    """Create the pip_scraps table."""
    logger.info("Running pip_scraps migration on %s", settings.DB_PATH)
    
    with managed_conn() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS pip_scraps (
                id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                scrap_type TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        
        # Create indexes for faster queries
        db.execute("CREATE INDEX IF NOT EXISTS idx_pip_scraps_type ON pip_scraps(scrap_type)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_pip_scraps_created ON pip_scraps(created_at)")
        
        db.commit()
    
    logger.info("Migration pip_scraps completed successfully.")

if __name__ == "__main__":
    run_migration()
