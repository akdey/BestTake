import os
import shutil
import logging
from pathlib import Path
from typing import List
from besttake.models import MediaMetadata

logger = logging.getLogger("BestTake")

class FileArchiver:
    """Handles directory creation, safe moves, renaming collisions, and symlink creation."""
    def __init__(self, scan_dir: Path, output_dir: Path, dry_run: bool = False):
        self.scan_dir = scan_dir
        self.output_dir = output_dir
        self.dry_run = dry_run

        self.keep_dir = output_dir / "keep"
        self.keep_me_dir = self.keep_dir / "me"
        self.keep_others_dir = self.keep_dir / "others"
        self.keep_scenery_dir = self.keep_dir / "scenery"

        self.duplicates_dir = output_dir / "duplicates"
        self.failed_dir = output_dir / "failed"

        if not self.dry_run:
            self.keep_me_dir.mkdir(parents=True, exist_ok=True)
            self.keep_others_dir.mkdir(parents=True, exist_ok=True)
            self.keep_scenery_dir.mkdir(parents=True, exist_ok=True)
            self.duplicates_dir.mkdir(parents=True, exist_ok=True)
            self.failed_dir.mkdir(parents=True, exist_ok=True)

    def _get_unique_dest_path(self, dest_dir: Path, original_name: str) -> Path:
        base, ext = os.path.splitext(original_name)
        dest_path = dest_dir / original_name
        counter = 1
        while dest_path.exists():
            dest_path = dest_dir / f"{base}_dup{counter}{ext}"
            counter += 1
        return dest_path

    def move_failed_file(self, file_path: str):
        src = Path(file_path)
        if not src.exists():
            return
        dest = self._get_unique_dest_path(self.failed_dir, src.name)
        logger.warning(f"Moving corrupt file to failed: {src} -> {dest}")
        if not self.dry_run:
            shutil.move(str(src), str(dest))

    def archive_duplicate_group(self, group_index: int, winner: MediaMetadata, losers: List[MediaMetadata]):
        group_dir = self.duplicates_dir / f"group_{group_index:03d}"
        if not self.dry_run:
            group_dir.mkdir(parents=True, exist_ok=True)

        winner_path = Path(winner.file_path)
        info_lines = [
            f"# Duplicate Group {group_index:03d}",
            f"\n## Selected Winner (Kept in original location)",
            f"- **Path**: {winner.file_path}",
            f"- **Size**: {winner.file_size} bytes",
            f"- **Resolution**: {winner.width}x{winner.height}",
            f"- **Sharpness**: {winner.sharpness}" if winner.sharpness else "",
            f"- **Duration**: {winner.duration:.2f}s" if winner.duration else "",
            f"- **MD5**: {winner.md5_hash}",
            f"- **Face Status Code**: {winner.me_present}",
            f"\n## Archived Duplicate(s) (Losers)"
        ]

        # 1. Create reference symlink to the Winner inside the duplicate group directory
        ref_symlink = group_dir / f"winner_ref_{winner_path.name}"
        if not self.dry_run:
            try:
                # If symlink already exists, remove it
                if ref_symlink.exists() or ref_symlink.is_symlink():
                    ref_symlink.unlink()
                # Create relative or absolute symlink
                ref_symlink.symlink_to(winner_path.resolve())
            except Exception as e:
                logger.debug(f"Failed to create winner reference symlink: {e}")

        # 2. Move each duplicate "loser" file
        for idx, loser in enumerate(losers, 1):
            loser_path = Path(loser.file_path)
            dest_path = self._get_unique_dest_path(group_dir, loser_path.name)
            
            info_lines.append(f"\n### Loser {idx}")
            info_lines.append(f"- **Original Path**: {loser.file_path}")
            info_lines.append(f"- **Moved To**: {dest_path.name}")
            info_lines.append(f"- **Size**: {loser.file_size} bytes")
            info_lines.append(f"- **Resolution**: {loser.width}x{loser.height}")
            info_lines.append(f"- **Sharpness**: {loser.sharpness}" if loser.sharpness else "")
            info_lines.append(f"- **MD5**: {loser.md5_hash}")
            info_lines.append(f"- **Face Status Code**: {loser.me_present}")

            logger.info(f"Moving duplicate loser: {loser_path} -> {dest_path}")
            if not self.dry_run:
                if loser_path.exists():
                    shutil.move(str(loser_path), str(dest_path))

        # Write group info markdown file
        if not self.dry_run:
            with open(group_dir / "group_info.md", "w") as f:
                f.write("\n".join(info_lines))

    def create_keep_symlink(self, media: MediaMetadata):
        """Creates a symlink inside the keep/ subdirectories (me, others, scenery) preserving relative structures."""
        src_path = Path(media.file_path)
        if not src_path.exists():
            return
        
        # Calculate relative path from scan directory to preserve tree structure
        try:
            rel_path = src_path.relative_to(self.scan_dir)
        except ValueError:
            rel_path = Path(src_path.name)

        # Decide keep folder based on me_present status
        if media.me_present == 1:
            target_keep_dir = self.keep_me_dir
        elif media.me_present == 2:
            target_keep_dir = self.keep_others_dir
        else:
            target_keep_dir = self.keep_scenery_dir

        dest_link = target_keep_dir / rel_path
        if not self.dry_run:
            dest_link.parent.mkdir(parents=True, exist_ok=True)
            try:
                if dest_link.exists() or dest_link.is_symlink():
                    dest_link.unlink()
                dest_link.symlink_to(src_path.resolve())
            except Exception as e:
                logger.debug(f"Failed to create keep symlink for {src_path}: {e}")
