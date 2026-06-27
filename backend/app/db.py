import json
import os
import logging
import sqlite3
import copy
from collections.abc import MutableMapping
from typing import Any, Dict, List

logger = logging.getLogger("genq_api.db")

class JobCancelledException(Exception):
    """Exception raised when a job is cancelled by the user."""
    pass


DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'reports.db'))

class PersistentJobProxy(dict):
    """A proxy dictionary that transparently persists mutations back to the parent database."""
    def __init__(self, parent_db, job_id, initial_data):
        super().__init__(initial_data)
        self._parent_db = parent_db
        self._job_id = job_id

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._parent_db._save_job(self._job_id, dict(self))

    def __delitem__(self, key):
        super().__delitem__(key)
        self._parent_db._save_job(self._job_id, dict(self))

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self._parent_db._save_job(self._job_id, dict(self))

    def pop(self, key, default=None):
        val = super().pop(key, default)
        self._parent_db._save_job(self._job_id, dict(self))
        return val


class PersistentReportsDB(MutableMapping):
    """A SQLite-backed dict-like mapping for reports, storing heavy fields on the filesystem."""
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
        except Exception:
            pass
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                )
            """)
            conn.commit()

        # Migrate from reports_store.json if it exists and SQLite table is empty
        json_file = os.path.join(os.path.dirname(__file__), '..', 'reports_store.json')
        if os.path.exists(json_file):
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM reports")
                    count = cursor.fetchone()[0]
                
                if count == 0:
                    logger.info("[DB] Migrating reports from reports_store.json to SQLite db...")
                    with open(json_file, 'r', encoding='utf-8') as f:
                        old_data = json.load(f)
                    
                    if old_data and isinstance(old_data, dict):
                        for key, val in old_data.items():
                            self[key] = val
                        logger.info(f"[DB] Successfully migrated {len(old_data)} reports.")
            except Exception as e:
                logger.error(f"[DB] Report migration failed: {e}")

    def __getitem__(self, key):
        # 1. Load the metadata from SQLite
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT data FROM reports WHERE id = ?", (key,))
            row = cursor.fetchone()
            if row is None:
                raise KeyError(key)
            report_data = json.loads(row[0])
            
        # 2. Load data_sample from filesystem if it exists
        sample_path = os.path.join(os.path.dirname(self.db_path), "data", "samples", f"{key}_sample.json")
        if os.path.exists(sample_path):
            try:
                with open(sample_path, "r", encoding="utf-8") as f:
                    report_data["data_sample"] = json.load(f)
            except Exception as e:
                logger.error(f"[DB] Failed to load data sample for {key}: {e}")
                report_data["data_sample"] = []
        else:
            report_data["data_sample"] = []
            
        # 3. Load chart_images from filesystem if it exists
        images_path = os.path.join(os.path.dirname(self.db_path), "data", "images", f"{key}_images.json")
        if os.path.exists(images_path):
            try:
                with open(images_path, "r", encoding="utf-8") as f:
                    chart_images = json.load(f)
                if "report" in report_data and isinstance(report_data["report"], dict):
                    if "_meta" not in report_data["report"] or not isinstance(report_data["report"]["_meta"], dict):
                        report_data["report"]["_meta"] = {}
                    report_data["report"]["_meta"]["chart_images"] = chart_images
            except Exception as e:
                logger.error(f"[DB] Failed to load chart images for {key}: {e}")
                
        return report_data

    def __setitem__(self, key, value):
        report_data = copy.deepcopy(value)
        
        # 1. Extract and save data_sample
        data_sample = report_data.pop("data_sample", None)
        if data_sample is not None:
            sample_dir = os.path.join(os.path.dirname(self.db_path), "data", "samples")
            os.makedirs(sample_dir, exist_ok=True)
            sample_path = os.path.join(sample_dir, f"{key}_sample.json")
            try:
                with open(sample_path, "w", encoding="utf-8") as f:
                    json.dump(data_sample, f, ensure_ascii=False)
            except Exception as e:
                logger.error(f"[DB] Failed to save data sample for {key}: {e}")
                
        # 2. Extract and save chart_images (from report -> _meta -> chart_images)
        chart_images = None
        if "report" in report_data and isinstance(report_data["report"], dict):
            _meta = report_data["report"].get("_meta", {})
            if isinstance(_meta, dict) and "chart_images" in _meta:
                chart_images = _meta.pop("chart_images", None)
                
        if chart_images is not None:
            images_dir = os.path.join(os.path.dirname(self.db_path), "data", "images")
            os.makedirs(images_dir, exist_ok=True)
            images_path = os.path.join(images_dir, f"{key}_images.json")
            try:
                with open(images_path, "w", encoding="utf-8") as f:
                    json.dump(chart_images, f, ensure_ascii=False)
            except Exception as e:
                logger.error(f"[DB] Failed to save chart images for {key}: {e}")
                
        # 3. Save the remaining metadata dictionary to SQLite
        data_str = json.dumps(report_data, ensure_ascii=False)
        with self._get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO reports (id, data) VALUES (?, ?)",
                (key, data_str)
            )
            conn.commit()

    def __delitem__(self, key):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM reports WHERE id = ?", (key,))
            if cursor.fetchone() is None:
                raise KeyError(key)
            conn.execute("DELETE FROM reports WHERE id = ?", (key,))
            conn.commit()
            
        # Delete associated filesystem files
        sample_path = os.path.join(os.path.dirname(self.db_path), "data", "samples", f"{key}_sample.json")
        if os.path.exists(sample_path):
            try:
                os.remove(sample_path)
            except Exception as e:
                logger.warning(f"[DB] Failed to delete data sample file {sample_path}: {e}")
                
        images_path = os.path.join(os.path.dirname(self.db_path), "data", "images", f"{key}_images.json")
        if os.path.exists(images_path):
            try:
                os.remove(images_path)
            except Exception as e:
                logger.warning(f"[DB] Failed to delete chart images file {images_path}: {e}")

    def __iter__(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM reports")
            keys = [row[0] for row in cursor.fetchall()]
        return iter(keys)

    def __len__(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM reports")
            return cursor.fetchone()[0]

    def items(self):
        keys = list(self.keys())
        return [(k, self[k]) for k in keys]

    def keys(self):
        return list(self.__iter__())

    def values(self):
        return [self[k] for k in self.keys()]

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM reports WHERE id = ?", (key,))
            return cursor.fetchone() is not None


class PersistentJobsDB(MutableMapping):
    """A Redis-backed dict-like mapping for active jobs, falling back to SQLite if Redis is unavailable."""
    def __init__(self, redis_url=None):
        self.redis_url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self.redis_client = None
        self._fallback_mode = False
        self.sqlite_path = DB_PATH
        
        try:
            import redis
            self.redis_client = redis.Redis.from_url(self.redis_url, decode_responses=True)
            self.redis_client.ping()
            logger.info(f"[DB] Connected to Redis at {self.redis_url} for job tracking.")
        except Exception as e:
            logger.debug(f"[DB] Redis unavailable ({e}).")
            logger.info("[DB] Redis not available — using SQLite for job tracking (set REDIS_URL to enable Redis).")
            self._fallback_mode = True
            self._init_sqlite_fallback()

    def _init_sqlite_fallback(self):
        conn = sqlite3.connect(self.sqlite_path, timeout=10.0)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                )
            """)
            conn.commit()
        except Exception as e:
            logger.error(f"[DB] Failed to init SQLite jobs table: {e}")
        finally:
            conn.close()
        self._cleanup_stale_jobs()

    def _cleanup_stale_jobs(self):
        """Mark any jobs left in non-terminal states as Failed (server restart recovery)."""
        conn = sqlite3.connect(self.sqlite_path, timeout=10.0)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'")
            if not cursor.fetchone():
                return

            cursor.execute("SELECT id, data FROM jobs")
            rows = cursor.fetchall()
            updated_count = 0
            for job_id, data_str in rows:
                try:
                    data = json.loads(data_str)
                    if data.get("status") not in ("Complete", "Failed", "Cancelled"):
                        data["status"] = "Failed"
                        data["error"] = "Server restarted during analysis"
                        conn.execute(
                            "INSERT OR REPLACE INTO jobs (id, data) VALUES (?, ?)",
                            (job_id, json.dumps(data, ensure_ascii=False))
                        )
                        updated_count += 1
                except Exception as ex:
                    logger.error(f"[DB] Error cleaning up job {job_id}: {ex}")
            if updated_count > 0:
                conn.commit()
                logger.info(f"[DB] Cleaned up {updated_count} stale jobs from database startup.")
        except Exception as e:
            logger.error(f"[DB] Failed to clean up stale jobs: {e}")
        finally:
            conn.close()

    def _save_job(self, job_id, data_dict):
        if not self._fallback_mode:
            try:
                self.redis_client.set(f"job:{job_id}", json.dumps(data_dict, ensure_ascii=False))
                return
            except Exception as e:
                logger.error(f"[DB] Redis write failed for job {job_id} ({e}). Switching to SQLite fallback.")
                self._fallback_mode = True
                self._init_sqlite_fallback()

        conn = sqlite3.connect(self.sqlite_path, timeout=10.0)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO jobs (id, data) VALUES (?, ?)",
                (job_id, json.dumps(data_dict, ensure_ascii=False))
            )
            conn.commit()
        except Exception as e:
            logger.error(f"[DB] SQLite write failed for job {job_id}: {e}")
        finally:
            conn.close()

    def __getitem__(self, key):
        if not self._fallback_mode:
            try:
                val = self.redis_client.get(f"job:{key}")
                if val is None:
                    raise KeyError(key)
                return PersistentJobProxy(self, key, json.loads(val))
            except KeyError:
                raise
            except Exception as e:
                logger.warning(f"[DB] Redis read failed for job {key} ({e}). Switching to SQLite fallback.")
                self._fallback_mode = True
                self._init_sqlite_fallback()

        conn = sqlite3.connect(self.sqlite_path, timeout=10.0)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT data FROM jobs WHERE id = ?", (key,))
            row = cursor.fetchone()
            if row is None:
                raise KeyError(key)
            return PersistentJobProxy(self, key, json.loads(row[0]))
        except sqlite3.Error as se:
            raise KeyError(key) from se
        finally:
            conn.close()

    def __setitem__(self, key, value):
        self._save_job(key, value)

    def __delitem__(self, key):
        if not self._fallback_mode:
            try:
                res = self.redis_client.delete(f"job:{key}")
                if res == 0:
                    raise KeyError(key)
                return
            except KeyError:
                raise
            except Exception as e:
                logger.warning(f"[DB] Redis delete failed for job {key} ({e}). Switching to SQLite fallback.")
                self._fallback_mode = True
                self._init_sqlite_fallback()

        conn = sqlite3.connect(self.sqlite_path, timeout=10.0)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM jobs WHERE id = ?", (key,))
            if cursor.fetchone() is None:
                raise KeyError(key)
            conn.execute("DELETE FROM jobs WHERE id = ?", (key,))
            conn.commit()
        except sqlite3.Error as se:
            raise KeyError(key) from se
        finally:
            conn.close()

    def __iter__(self):
        if not self._fallback_mode:
            try:
                keys = self.redis_client.keys("job:*")
                return iter([k.split("job:", 1)[1] for k in keys])
            except Exception as e:
                logger.warning(f"[DB] Redis iteration failed ({e}). Switching to SQLite fallback.")
                self._fallback_mode = True
                self._init_sqlite_fallback()

        conn = sqlite3.connect(self.sqlite_path, timeout=10.0)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM jobs")
            keys = [row[0] for row in cursor.fetchall()]
            return iter(keys)
        except sqlite3.Error:
            return iter([])
        finally:
            conn.close()

    def __len__(self):
        if not self._fallback_mode:
            try:
                keys = self.redis_client.keys("job:*")
                return len(keys)
            except Exception as e:
                logger.warning(f"[DB] Redis count failed ({e}). Switching to SQLite fallback.")
                self._fallback_mode = True
                self._init_sqlite_fallback()

        conn = sqlite3.connect(self.sqlite_path, timeout=10.0)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM jobs")
            return cursor.fetchone()[0]
        except sqlite3.Error:
            return 0
        finally:
            conn.close()

    def items(self):
        if not self._fallback_mode:
            try:
                keys = self.redis_client.keys("job:*")
                items_list = []
                for k in keys:
                    job_id = k.split("job:", 1)[1]
                    val = self.redis_client.get(k)
                    if val:
                        items_list.append((job_id, PersistentJobProxy(self, job_id, json.loads(val))))
                return items_list
            except Exception as e:
                logger.warning(f"[DB] Redis items failed ({e}). Switching to SQLite fallback.")
                self._fallback_mode = True
                self._init_sqlite_fallback()

        conn = sqlite3.connect(self.sqlite_path, timeout=10.0)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, data FROM jobs")
            rows = cursor.fetchall()
            return [(row[0], PersistentJobProxy(self, row[0], json.loads(row[1]))) for row in rows]
        except sqlite3.Error:
            return []
        finally:
            conn.close()

    def values(self):
        return [item[1] for item in self.items()]

    def keys(self):
        return list(self.__iter__())

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key):
        if not self._fallback_mode:
            try:
                return self.redis_client.exists(f"job:{key}") > 0
            except Exception as e:
                logger.warning(f"[DB] Redis exists check failed ({e}). Switching to SQLite fallback.")
                self._fallback_mode = True
                self._init_sqlite_fallback()

        conn = sqlite3.connect(self.sqlite_path, timeout=10.0)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM jobs WHERE id = ?", (key,))
            return cursor.fetchone() is not None
        except sqlite3.Error:
            return False
        finally:
            conn.close()


reports_db = PersistentReportsDB()
jobs = PersistentJobsDB()
