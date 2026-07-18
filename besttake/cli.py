import os
import sys
import argparse
import logging
import multiprocessing
from pathlib import Path

from besttake.models import MediaMetadata
from besttake.database import DatabaseHandler
from besttake.processor import process_media_worker, init_worker
from besttake.clustering import MediaClusterer
from besttake.scoring import QualityEvaluator
from besttake.archiver import FileArchiver

# Setup Logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("BestTake")

# Supported media extensions (case-insensitive)
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.mov', '.avi'}

def write_summary_report(output_path, singletons, all_winners, resolved_groups, failed_files, face_filtering_enabled, space_saved, scan_path):
    report_file = output_path / "summary_report.md"
    
    keepers_me = []
    keepers_others = []
    keepers_scenery = []
    keepers_review = []
    
    def add_to_keepers(meta):
        if meta.me_present == 1:
            keepers_me.append(meta)
        elif meta.me_present == 2:
            keepers_others.append(meta)
        elif meta.me_present == 3:
            keepers_review.append(meta)
        else:
            keepers_scenery.append(meta)
            
    for m in singletons:
        add_to_keepers(m)
    for m in all_winners:
        add_to_keepers(m)
        
    total_scanned = len(singletons) + len(all_winners) + sum(len(losers) for _, losers in resolved_groups) + len(failed_files)
    
    lines = [
        "# BestTake Reorganization & Deduplication Report\n",
        "## Execution Summary\n",
        f"- **Scan Directory**: `{scan_path}`",
        f"- **Output Directory**: `{output_path}`",
        f"- **Total Scanned Files**: {total_scanned}",
        f"- **Total Kept Files**: {len(singletons) + len(all_winners)}",
        f"  - **Kept (Me)**: {len(keepers_me)}",
        f"  - **Kept (Others)**: {len(keepers_others)}",
        f"  - **Kept (Scenery)**: {len(keepers_scenery)}",
        f"  - **Kept (Review)**: {len(keepers_review)}",
        f"- **Isolated Duplicates**: {sum(len(losers) for _, losers in resolved_groups)}",
        f"- **Failed / Unreadable Files**: {len(failed_files)}",
        f"- **Estimated Space Saved**: {space_saved / (1024 * 1024):.2f} MB ({space_saved} bytes)",
        f"- **Face Filtering Module**: {'ACTIVE' if face_filtering_enabled else 'INACTIVE'}\n",
        "---\n",
        "## Detailed Breakdown\n"
    ]
    
    # 1. Me
    lines.append("### 1. Kept Files with My Face (`keep/me/`)\n")
    if keepers_me:
        lines.append("| Original Path | Size | Resolution | Sharpness |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for m in sorted(keepers_me, key=lambda x: x.file_path):
            res_str = f"{m.width}x{m.height}" if m.width else "N/A"
            sharp_str = f"{m.sharpness:.2f}" if m.sharpness else "N/A"
            lines.append(f"| `{m.file_path}` | {m.file_size} bytes | {res_str} | {sharp_str} |")
    else:
        lines.append("*No files found.*\n")
    lines.append("")
    
    # 2. Others
    lines.append("### 2. Kept Files with Others' Faces (`keep/others/`)\n")
    if keepers_others:
        lines.append("| Original Path | Size | Resolution |")
        lines.append("| :--- | :--- | :--- |")
        for m in sorted(keepers_others, key=lambda x: x.file_path):
            res_str = f"{m.width}x{m.height}" if m.width else "N/A"
            lines.append(f"| `{m.file_path}` | {m.file_size} bytes | {res_str} |")
    else:
        lines.append("*No files found.*\n")
    lines.append("")

    # 3. Scenery
    lines.append("### 3. Kept Scenery Files (`keep/scenery/`)\n")
    if keepers_scenery:
        lines.append("| Original Path | Size |")
        lines.append("| :--- | :--- |")
        for m in sorted(keepers_scenery, key=lambda x: x.file_path):
            lines.append(f"| `{m.file_path}` | {m.file_size} bytes |")
    else:
        lines.append("*No files found.*\n")
    lines.append("")

    # 4. Review
    lines.append("### 4. Low Quality / Blurry Review Files (`keep/review/`)\n")
    if keepers_review:
        lines.append("| Original Path | Size | Sharpness |")
        lines.append("| :--- | :--- | :--- |")
        for m in sorted(keepers_review, key=lambda x: x.file_path):
            sharp_str = f"{m.sharpness:.2f}" if m.sharpness else "N/A"
            lines.append(f"| `{m.file_path}` | {m.file_size} bytes | {sharp_str} |")
    else:
        lines.append("*No blurry files found.*\n")
    lines.append("")

    # 5. Failed
    lines.append("### 5. Failed / Unreadable Media (`failed/`)\n")
    if failed_files:
        lines.append("| File Path |")
        lines.append("| :--- |")
        for path in sorted(failed_files):
            lines.append(f"| `{path}` |")
    else:
        lines.append("*No failures.*")
    lines.append("")

    # 6. Duplicates
    lines.append("### 6. Duplicate Groups (`duplicates/`)\n")
    if resolved_groups:
        for idx, (winner, losers) in enumerate(resolved_groups, 1):
            lines.append(f"#### Group {idx:03d}")
            lines.append(f"- **Winner (Kept)**: `{winner.file_path}` ({winner.width}x{winner.height}, {winner.file_size} bytes, face status: {winner.me_present})")
            lines.append("- **Duplicate(s) (Moved to archive)**:")
            for l in losers:
                lines.append(f"  - `{l.file_path}` ({l.width}x{l.height}, {l.file_size} bytes, face status: {l.me_present})")
            lines.append("")
    else:
        lines.append("*No duplicates found.*\n")

    try:
        with open(report_file, "w") as f:
            f.write("\n".join(lines))
        logger.info(f"Summary report written to {report_file}")
    except Exception as e:
        logger.error(f"Failed to write summary report: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="BestTake: Smart AI Media Deduplicator and Face Classifier."
    )
    parser.add_argument("scan_dir", type=str, nargs="?", default=None,
                        help="Target directory to recursively scan.")
    parser.add_argument("--web", action="store_true",
                        help="Launch the BestTake Web Application UI in your browser.")
    parser.add_argument("--host", type=str, default="127.0.0.1",
                        help="Host IP address for Web UI (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8000,
                        help="Port for Web UI (default: 8000).")
    parser.add_argument("--db", type=str, default=None,
                        help="Path to SQLite cache DB (defaults to media_cache.db in script root).")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Path to output folder (defaults to _best_take_output in the scan directory).")
    parser.add_argument("--threshold", type=int, default=4,
                        help="Max Hamming distance threshold for perceptual similarity (default: 4).")
    parser.add_argument("--face-tolerance", type=float, default=0.48,
                        help="Face match distance tolerance (lower is stricter, default: 0.48).")
    parser.add_argument("--review-sharpness", type=float, default=50.0,
                        help="Laplacian variance sharpness threshold for review folder (default: 50.0).")
    parser.add_argument("--duration-tolerance", type=float, default=0.1,
                        help="Video duration tolerance in seconds for similarity (default: 0.1).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run detection and print summary without performing file modifications.")
    parser.add_argument("--verbose", action="store_true",
                        help="Print detailed debug messages.")

    args = parser.parse_args()

    if args.web:
        import uvicorn
        import webbrowser
        url = f"http://{args.host}:{args.port}"
        logger.info(f"Launching BestTake Web Interface on {url} ...")
        webbrowser.open(url)
        uvicorn.run("besttake.web:app", host=args.host, port=args.port, reload=False)
        sys.exit(0)

    if not args.scan_dir:
        parser.print_help()
        sys.exit(1)

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    scan_path = Path(args.scan_dir).resolve()
    if not scan_path.exists() or not scan_path.is_dir():
        logger.error(f"Scan directory does not exist or is not a directory: {scan_path}")
        sys.exit(1)

    script_dir = Path(__file__).resolve().parent.parent
    db_path = Path(args.db).resolve() if args.db else script_dir / "media_cache.db"
    logger.info(f"Using database cache: {db_path}")
    db_handler = DatabaseHandler(db_path)

    output_path = Path(args.output_dir).resolve() if args.output_dir else scan_path / "_best_take_output"
    logger.info(f"Using output/archive directory: {output_path}")

    known_face_encodings = []
    me_ref_path = Path("me_references")
    face_filtering_enabled = False

    if me_ref_path.exists() and me_ref_path.is_dir():
        logger.info("Checking face references folder (me_references/)...")
        try:
            import face_recognition
            ref_exts = {'.jpg', '.jpeg', '.png', '.webp'}
            ref_files = [f for f in me_ref_path.iterdir() if f.suffix.lower() in ref_exts]
            
            for ref_file in ref_files:
                try:
                    image = face_recognition.load_image_file(str(ref_file))
                    # Upsample 2x to detect small or angled faces
                    face_locations = face_recognition.face_locations(image, number_of_times_to_upsample=2)
                    if len(face_locations) == 1:
                        encs = face_recognition.face_encodings(image, face_locations)
                        if encs:
                            known_face_encodings.append(encs[0])
                            logger.info(f"Loaded face reference: {ref_file.name}")
                    else:
                        logger.warning(
                            f"Skipping reference image {ref_file.name}: "
                            f"Must contain exactly one detectable face (found {len(face_locations)})."
                        )
                except Exception as ex:
                    logger.warning(f"Failed to process reference image {ref_file.name}: {ex}")
            
            if known_face_encodings:
                logger.info(f"Loaded {len(known_face_encodings)} face embeddings. Face Filtering: ACTIVE.")
                face_filtering_enabled = True
            else:
                logger.warning("No valid face reference images loaded. Face Filtering: INACTIVE.")
        except ImportError:
            logger.warning(
                "face_recognition library not found. Please install cmake and face_recognition. "
                "Face Filtering: INACTIVE."
            )
    else:
        logger.info("Face Filtering: INACTIVE (me_references/ directory not found in execution root).")

    cached_metadata = db_handler.get_cached_metadata()
    logger.info(f"Loaded {len(cached_metadata)} records from database cache.")

    logger.info(f"Scanning target directory: {scan_path}")
    
    exclude_paths = {output_path}
    files_to_process = []
    valid_scanned_metadata = []
    visited_paths = set()
    failed_files = []

    for root, dirs, files in os.walk(scan_path):
        current_dir = Path(root).resolve()
        
        if any(current_dir == p or p in current_dir.parents for p in exclude_paths):
            continue

        for filename in files:
            if filename.startswith('.'):
                continue

            file_path = current_dir / filename
            ext = file_path.suffix.lower()
            
            if ext in IMAGE_EXTENSIONS:
                file_type = 'image'
            elif ext in VIDEO_EXTENSIONS:
                file_type = 'video'
            else:
                continue

            visited_paths.add(str(file_path))

            try:
                file_size = file_path.stat().st_size
                mtime = file_path.stat().st_mtime
            except OSError as e:
                logger.error(f"Cannot read file stats for {file_path}: {e}")
                failed_files.append(str(file_path))
                continue

            cached = cached_metadata.get(str(file_path))
            if cached and cached.file_size == file_size and cached.modified_time == mtime:
                valid_scanned_metadata.append(cached)
            else:
                files_to_process.append((str(file_path), file_type))

    logger.info(f"Walk complete. Found {len(visited_paths)} total media files.")
    logger.info(f"{len(valid_scanned_metadata)} cached hits. {len(files_to_process)} files need processing.")

    stale_paths = set(cached_metadata.keys()) - visited_paths
    if stale_paths:
        logger.info(f"Removing {len(stale_paths)} stale entries from database cache.")
        db_handler.remove_paths(list(stale_paths))

    processed_results = []
    if files_to_process:
        num_cores = multiprocessing.cpu_count()
        logger.info(f"Launching processing queue with {len(files_to_process)} items using {num_cores} workers...")
        
        with multiprocessing.Pool(
            processes=num_cores,
            initializer=init_worker,
            initargs=(known_face_encodings, args.face_tolerance, args.review_sharpness)
        ) as pool:
            for index, res in enumerate(pool.imap_unordered(process_media_worker, files_to_process), 1):
                if res['status'] == 'success':
                    meta = MediaMetadata(
                        file_path=res['file_path'],
                        file_type=res['file_type'],
                        file_size=res['file_size'],
                        modified_time=res['modified_time'],
                        md5_hash=res['md5_hash'],
                        perceptual_hash=res['perceptual_hash'],
                        duration=res['duration'],
                        width=res['width'],
                        height=res['height'],
                        sharpness=res['sharpness'],
                        me_present=res['me_present']
                    )
                    processed_results.append(meta)
                    valid_scanned_metadata.append(meta)
                    if index % 50 == 0 or index == len(files_to_process):
                        logger.info(f"Processed {index}/{len(files_to_process)} files...")
                else:
                    logger.error(f"Processing failed for {res['file_path']}: {res['error']}")
                    failed_files.append(res['file_path'])

        if processed_results:
            logger.info(f"Saving {len(processed_results)} newly processed records to cache DB.")
            db_handler.save_metadata_batch(processed_results)

    logger.info("Running clustering algorithms...")
    duplicate_clusters = MediaClusterer.cluster(
        valid_scanned_metadata,
        threshold=args.threshold,
        duration_tolerance=args.duration_tolerance
    )

    all_losers = []
    all_winners = []
    duplicate_count = 0
    space_saved = 0

    archiver = FileArchiver(scan_path, output_path, dry_run=args.dry_run)

    for failed_path in failed_files:
        archiver.move_failed_file(failed_path)

    resolved_groups = []
    for group_idx, cluster in enumerate(duplicate_clusters, 1):
        winner, losers = QualityEvaluator.resolve_cluster(cluster)
        all_winners.append(winner)
        all_losers.extend(losers)
        duplicate_count += len(losers)
        space_saved += sum(l.file_size for l in losers)
        
        archiver.archive_duplicate_group(group_idx, winner, losers)
        resolved_groups.append((winner, losers))

    grouped_paths = {m.file_path for cluster in duplicate_clusters for m in cluster}
    failed_paths_set = set(failed_files)
    singletons = [
        meta for meta in valid_scanned_metadata 
        if meta.file_path not in grouped_paths and meta.file_path not in failed_paths_set
    ]

    for singleton in singletons:
        archiver.create_keep_symlink(singleton)
    for winner in all_winners:
        archiver.create_keep_symlink(winner)

    if not args.dry_run:
        write_summary_report(
            output_path, singletons, all_winners, resolved_groups,
            failed_files, face_filtering_enabled, space_saved, scan_path
        )

    print("\n" + "="*50)
    print("BESTTAKE EXECUTION SUMMARY")
    print("="*50)
    print(f"Total Scanned Files:         {len(visited_paths)}")
    print(f"Unique Files / Winners:      {len(singletons) + len(all_winners)}")
    print(f"Isolated Duplicate Files:    {duplicate_count}")
    print(f"Failed / Unreadable Files:   {len(failed_files)}")
    print(f"Estimated Space Saved:       {space_saved / (1024 * 1024):.2f} MB ({space_saved} bytes)")
    print(f"Face Filtering:              {'ACTIVE' if face_filtering_enabled else 'INACTIVE'}")
    print(f"Output Directory:            {output_path}")
    if args.dry_run:
        print("\n*** DRY RUN ONLY - No files were actually moved or modified. ***")
    print("="*50)

if __name__ == "__main__":
    main()
