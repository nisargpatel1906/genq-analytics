import json
import os
import logging

logger = logging.getLogger("genq_api.db")

DB_FILE = os.path.join(os.path.dirname(__file__), '..', 'reports_store.json')

# In-memory job tracking (ephemeral, fine for active uploads)
jobs = {}

def _load_reports() -> dict:
    """Load reports from disk."""
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save_reports(db: dict):
    """Persist reports to disk."""
    try:
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"[DB] Failed to save reports: {e}")

class PersistentReportsDB(dict):
    """A dict that automatically persists on writes."""
    def __init__(self):
        super().__init__(_load_reports())

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        _save_reports(dict(self))

    def __delitem__(self, key):
        super().__delitem__(key)
        _save_reports(dict(self))

reports_db = PersistentReportsDB()
