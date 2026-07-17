import unittest
import tempfile
import shutil
import os
from pathlib import Path
import cv2
import numpy as np
from PIL import Image

# Import the besttake package modules
from besttake.models import MediaMetadata
from besttake.clustering import UnionFind, MediaClusterer
from besttake.scoring import QualityEvaluator
from besttake.archiver import FileArchiver
from besttake.processor import process_media_worker, compute_md5
from besttake.database import DatabaseHandler


class TestBestTake(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for file operations
        self.test_dir = Path(tempfile.mkdtemp())
        self.scan_dir = self.test_dir / "scan"
        self.scan_dir.mkdir()
        self.output_dir = self.test_dir / "output"
        self.output_dir.mkdir()

    def tearDown(self):
        # Clean up all created files
        shutil.rmtree(self.test_dir)

    def test_union_find(self):
        uf = UnionFind(['a', 'b', 'c', 'd'])
        uf.union('a', 'b')
        uf.union('b', 'c')
        self.assertEqual(uf.find('a'), uf.find('c'))
        self.assertNotEqual(uf.find('a'), uf.find('d'))
        self.assertEqual(uf.find('b'), uf.find('c'))

    def test_image_quality_key(self):
        # Tie-breaker order: Resolution -> Sharpness -> File Size
        m1 = MediaMetadata("p1.jpg", "image", 100, 1.0, "md5_1", "h1", width=100, height=100, sharpness=10.0)
        m2 = MediaMetadata("p2.jpg", "image", 120, 1.0, "md5_2", "h2", width=100, height=100, sharpness=10.0)
        m3 = MediaMetadata("p3.jpg", "image", 120, 1.0, "md5_3", "h3", width=100, height=100, sharpness=15.0)
        m4 = MediaMetadata("p4.jpg", "image", 120, 1.0, "md5_4", "h4", width=200, height=100, sharpness=5.0)

        # m4 has higher resolution -> winner
        winner, losers = QualityEvaluator.resolve_cluster([m1, m2, m3, m4])
        self.assertEqual(winner.file_path, "p4.jpg")

        # m3 has higher sharpness than m2 -> winner
        winner2, losers2 = QualityEvaluator.resolve_cluster([m1, m2, m3])
        self.assertEqual(winner2.file_path, "p3.jpg")

        # m2 has larger file size than m1 -> winner
        winner3, losers3 = QualityEvaluator.resolve_cluster([m1, m2])
        self.assertEqual(winner3.file_path, "p2.jpg")

    def test_video_quality_key(self):
        # Tie-breaker order: Resolution -> File Size
        m1 = MediaMetadata("p1.mp4", "video", 1000, 1.0, "md5_1", "h1", duration=5.0, width=640, height=480)
        m2 = MediaMetadata("p2.mp4", "video", 2000, 1.0, "md5_2", "h2", duration=5.0, width=640, height=480)
        m3 = MediaMetadata("p3.mp4", "video", 1500, 1.0, "md5_3", "h3", duration=5.0, width=1280, height=720)

        # m3 has higher resolution -> winner
        winner, losers = QualityEvaluator.resolve_cluster([m1, m2, m3])
        self.assertEqual(winner.file_path, "p3.mp4")

        # m2 has larger file size -> winner
        winner2, losers2 = QualityEvaluator.resolve_cluster([m1, m2])
        self.assertEqual(winner2.file_path, "p2.mp4")

    def test_clustering_exact_match(self):
        m1 = MediaMetadata("p1.jpg", "image", 100, 1.0, "md5_same", "ffffffffffffffff", width=100, height=100)
        m2 = MediaMetadata("p2.jpg", "image", 100, 1.0, "md5_same", "ffffffffffffffff", width=100, height=100)
        m3 = MediaMetadata("p3.jpg", "image", 200, 1.0, "md5_diff", "0000000000000000", width=100, height=100)

        clusters = MediaClusterer.cluster([m1, m2, m3])
        self.assertEqual(len(clusters), 1)
        self.assertEqual(set(m.file_path for m in clusters[0]), {"p1.jpg", "p2.jpg"})

    def test_clustering_image_perceptual(self):
        m_a = MediaMetadata("pa.jpg", "image", 100, 1.0, "md5_a", "ffffffffffffffff", width=100, height=100)
        m_b = MediaMetadata("pb.jpg", "image", 100, 1.0, "md5_b", "fffffffffffffff0", width=100, height=100)  # Hamming dist 4 (0 vs f)
        m_c = MediaMetadata("pc.jpg", "image", 100, 1.0, "md5_c", "0000000000000000", width=100, height=100)  # Hamming dist 64

        clusters = MediaClusterer.cluster([m_a, m_b, m_c], threshold=4)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(set(m.file_path for m in clusters[0]), {"pa.jpg", "pb.jpg"})

    def test_clustering_video_perceptual(self):
        # 5 frame hashes matching almost identically
        h1 = "ffffffffffffffff,ffffffffffffffff,ffffffffffffffff,ffffffffffffffff,ffffffffffffffff"
        h2 = "ffffffffffffffff,ffffffffffffffff,ffffffffffffffff,ffffffffffffffff,fffffffffffffff0"  # avg dist = 4/5 = 0.8 <= 4
        h3 = "0000000000000000,0000000000000000,0000000000000000,0000000000000000,0000000000000000"

        v1 = MediaMetadata("v1.mp4", "video", 5000, 1.0, "md5_v1", h1, duration=10.0, width=640, height=480)
        v2 = MediaMetadata("v2.mp4", "video", 4800, 1.0, "md5_v2", h2, duration=10.05, width=640, height=480)  # within duration tolerance (0.1)
        v3 = MediaMetadata("v3.mp4", "video", 5000, 1.0, "md5_v3", h3, duration=10.0, width=640, height=480)
        v4 = MediaMetadata("v4.mp4", "video", 4800, 1.0, "md5_v4", h2, duration=10.5, width=640, height=480)   # duration diff 0.5s > tolerance (0.1)

        clusters = MediaClusterer.cluster([v1, v2, v3, v4], threshold=4, duration_tolerance=0.1)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(set(m.file_path for m in clusters[0]), {"v1.mp4", "v2.mp4"})

    def test_process_image_worker(self):
        # Generate a small image using PIL
        img_path = self.scan_dir / "test_image.jpg"
        img = Image.new("RGB", (100, 100), color="blue")
        img.save(img_path)

        res = process_media_worker((str(img_path), "image"))
        self.assertEqual(res['status'], 'success')
        self.assertEqual(res['width'], 100)
        self.assertEqual(res['height'], 100)
        self.assertEqual(res['file_type'], 'image')
        self.assertIsNotNone(res['sharpness'])
        self.assertEqual(len(res['perceptual_hash']), 16)

    def test_process_video_worker(self):
        # Generate a small video using OpenCV VideoWriter
        vid_path = self.scan_dir / "test_video.avi"
        fourcc = cv2.VideoWriter_fourcc(*'MJPG')
        out = cv2.VideoWriter(str(vid_path), fourcc, 10.0, (100, 100))

        # Write 20 frames
        for i in range(20):
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            frame[:, :] = [i * 12, 100, 255 - i * 12]
            out.write(frame)
        out.release()

        res = process_media_worker((str(vid_path), "video"))
        self.assertEqual(res['status'], 'success')
        self.assertEqual(res['width'], 100)
        self.assertEqual(res['height'], 100)
        self.assertEqual(res['file_type'], 'video')
        hashes = res['perceptual_hash'].split(',')
        self.assertEqual(len(hashes), 5)

    def test_file_archiver_moves_and_links(self):
        # Create mock file in scan directory
        img_path = self.scan_dir / "duplicate.jpg"
        img = Image.new("RGB", (100, 100), color="red")
        img.save(img_path)

        winner = MediaMetadata(
            file_path="nonexistent_winner.jpg",  # Winner kept untouched (pretend it's elsewhere)
            file_type="image",
            file_size=100,
            modified_time=1.0,
            md5_hash="md5_winner",
            perceptual_hash="ffffffffffffffff",
            width=100,
            height=100
        )
        loser = MediaMetadata(
            file_path=str(img_path),
            file_type="image",
            file_size=100,
            modified_time=1.0,
            md5_hash="md5_loser",
            perceptual_hash="ffffffffffffffff",
            width=100,
            height=100
        )

        archiver = FileArchiver(self.scan_dir, self.output_dir, dry_run=False)
        archiver.archive_duplicate_group(1, winner, [loser])

        # Assert duplicate was moved to duplicates/group_001/duplicate.jpg
        moved_file = self.output_dir / "duplicates" / "group_001" / "duplicate.jpg"
        self.assertTrue(moved_file.exists())
        self.assertFalse(img_path.exists())  # Loser moved out

        # Assert group_info.md and winner_ref exists
        info_file = self.output_dir / "duplicates" / "group_001" / "group_info.md"
        self.assertTrue(info_file.exists())

        # Test keep folder link segregation
        singleton_path = self.scan_dir / "unique.jpg"
        singleton_img = Image.new("RGB", (100, 100), color="green")
        singleton_img.save(singleton_path)

        # 1. Scenery (me_present = 0)
        singleton_scenery = MediaMetadata(
            file_path=str(singleton_path),
            file_type="image",
            file_size=150,
            modified_time=1.0,
            md5_hash="md5_singleton",
            perceptual_hash="0000000000000000",
            width=100,
            height=100,
            me_present=0
        )
        archiver.create_keep_symlink(singleton_scenery)
        keep_link_scenery = self.output_dir / "keep" / "scenery" / "unique.jpg"
        self.assertTrue(keep_link_scenery.is_symlink())
        self.assertEqual(keep_link_scenery.resolve(), singleton_path.resolve())

        # 2. Me (me_present = 1)
        singleton_me = MediaMetadata(
            file_path=str(singleton_path),
            file_type="image",
            file_size=150,
            modified_time=1.0,
            md5_hash="md5_singleton",
            perceptual_hash="0000000000000000",
            width=100,
            height=100,
            me_present=1
        )
        archiver.create_keep_symlink(singleton_me)
        keep_link_me = self.output_dir / "keep" / "me" / "unique.jpg"
        self.assertTrue(keep_link_me.is_symlink())
        self.assertEqual(keep_link_me.resolve(), singleton_path.resolve())

        # 3. Others (me_present = 2)
        singleton_others = MediaMetadata(
            file_path=str(singleton_path),
            file_type="image",
            file_size=150,
            modified_time=1.0,
            md5_hash="md5_singleton",
            perceptual_hash="0000000000000000",
            width=100,
            height=100,
            me_present=2
        )
        archiver.create_keep_symlink(singleton_others)
        keep_link_others = self.output_dir / "keep" / "others" / "unique.jpg"
        self.assertTrue(keep_link_others.is_symlink())
        self.assertEqual(keep_link_others.resolve(), singleton_path.resolve())

    def test_winner_selection_override(self):
        m1 = MediaMetadata("p1.jpg", "image", 200, 1.0, "md5_1", "h1", width=640, height=480, me_present=1)
        m2 = MediaMetadata("p2.jpg", "image", 100, 1.0, "md5_2", "h2", width=320, height=240, me_present=1)
        m3 = MediaMetadata("p3.jpg", "image", 500, 1.0, "md5_3", "h3", width=1280, height=720, me_present=0)

        winner, losers = QualityEvaluator.resolve_cluster([m1, m2, m3])
        self.assertEqual(winner.file_path, "p1.jpg")
        self.assertEqual(len(losers), 2)
        self.assertEqual(set(m.file_path for m in losers), {"p2.jpg", "p3.jpg"})

        m1_no = MediaMetadata("p1.jpg", "image", 200, 1.0, "md5_1", "h1", width=640, height=480, me_present=0)
        m2_no = MediaMetadata("p2.jpg", "image", 100, 1.0, "md5_2", "h2", width=320, height=240, me_present=0)
        m3_no = MediaMetadata("p3.jpg", "image", 500, 1.0, "md5_3", "h3", width=1280, height=720, me_present=0)

        winner2, losers2 = QualityEvaluator.resolve_cluster([m1_no, m2_no, m3_no])
        self.assertEqual(winner2.file_path, "p3.jpg")

    def test_database_migration(self):
        import sqlite3
        db_file = self.test_dir / "test_migration.db"
        with sqlite3.connect(db_file) as conn:
            conn.execute("""
                CREATE TABLE media_metadata (
                    file_path TEXT PRIMARY KEY,
                    file_type TEXT,
                    file_size INTEGER,
                    modified_time REAL,
                    md5_hash TEXT,
                    perceptual_hash TEXT,
                    duration REAL,
                    width INTEGER,
                    height INTEGER,
                    sharpness REAL
                )
            """)
            conn.execute("""
                INSERT INTO media_metadata VALUES (
                    'old_file.jpg', 'image', 100, 1.0, 'md5', 'hash', NULL, 100, 100, 10.0
                )
            """)
            conn.commit()

        # DatabaseHandler instantiation triggers migration
        handler = DatabaseHandler(db_file)

        with sqlite3.connect(db_file) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(media_metadata)")
            columns = [info[1] for info in cursor.fetchall()]
            self.assertIn('me_present', columns)

            cursor.execute("SELECT me_present FROM media_metadata WHERE file_path = 'old_file.jpg'")
            row = cursor.fetchone()
            self.assertEqual(row[0], 0)


if __name__ == '__main__':
    unittest.main()
