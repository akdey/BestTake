import sqlite3
from pathlib import Path
from typing import List, Dict
from besttake.models import MediaMetadata

class DatabaseHandler:
    """Manages SQLite cache initialization, querying, and bulk saving."""
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS media_metadata (
                    file_path TEXT PRIMARY KEY,
                    file_type TEXT,
                    file_size INTEGER,
                    modified_time REAL,
                    md5_hash TEXT,
                    perceptual_hash TEXT,
                    duration REAL,
                    width INTEGER,
                    height INTEGER,
                    sharpness REAL,
                    me_present INTEGER DEFAULT 0
                )
            """)
            conn.commit()

            # Schema Migration Check: If table exists but lacks 'me_present' column, add it.
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(media_metadata)")
            columns = [info[1] for info in cursor.fetchall()]
            if 'me_present' not in columns:
                conn.execute("ALTER TABLE media_metadata ADD COLUMN me_present INTEGER DEFAULT 0")
                conn.commit()

    def get_cached_metadata(self) -> Dict[str, MediaMetadata]:
        cached = {}
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT file_path, file_type, file_size, modified_time, md5_hash,
                       perceptual_hash, duration, width, height, sharpness, me_present 
                FROM media_metadata
            """)
            for row in cursor.fetchall():
                meta = MediaMetadata.from_db_row(row)
                cached[meta.file_path] = meta
        return cached

    def save_metadata_batch(self, metadata_list: List[MediaMetadata]):
        if not metadata_list:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO media_metadata (
                    file_path, file_type, file_size, modified_time, md5_hash,
                    perceptual_hash, duration, width, height, sharpness, me_present
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [m.to_db_tuple() for m in metadata_list])
            conn.commit()

    def remove_paths(self, paths: List[str]):
        if not paths:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany("DELETE FROM media_metadata WHERE file_path = ?", [(p,) for p in paths])
            conn.commit()
