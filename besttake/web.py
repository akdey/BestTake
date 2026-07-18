import os
import sys
import shutil
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional
from threading import Thread

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from besttake.models import MediaMetadata
from besttake.database import DatabaseHandler
from besttake.processor import process_media_worker, init_worker
from besttake.clustering import MediaClusterer
from besttake.scoring import QualityEvaluator
from besttake.archiver import FileArchiver

logger = logging.getLogger("BestTakeWeb")

app = FastAPI(title="BestTake Web Interface", version="1.0.0")

# Static directory setup
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Shared Scan Progress State
scan_state = {
    "running": False,
    "current": 0,
    "total": 0,
    "message": "Idle",
    "summary": None,
    "output_dir": None,
    "scan_dir": None
}

class ScanRequest(BaseModel):
    scan_dir: str
    threshold: int = 4
    duration_tolerance: float = 0.1
    dry_run: bool = False


@app.get("/")
def read_root():
    """Serve SPA index.html."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse({"message": "BestTake Backend Active. Web UI template initializing..."})


# --- Reference Face Management Endpoints ---

@app.get("/api/references")
def get_references():
    """Lists reference photos in me_references/ with face detection metadata."""
    ref_dir = Path("me_references")
    ref_dir.mkdir(parents=True, exist_ok=True)

    supported_exts = {'.jpg', '.jpeg', '.png', '.webp'}
    ref_files = [f for f in ref_dir.iterdir() if f.suffix.lower() in supported_exts]

    results = []
    for f in ref_files:
        face_count = 0
        status = "valid"
        error_msg = ""

        try:
            file_size = f.stat().st_size
        except Exception:
            continue

        try:
            import face_recognition
            img = face_recognition.load_image_file(str(f))
            locs = face_recognition.face_locations(img)
            face_count = len(locs)
            if face_count != 1:
                status = "warning"
                error_msg = f"Found {face_count} face(s). Exactly 1 face required."
        except Exception as e:
            status = "error"
            error_msg = str(e)

        results.append({
            "filename": f.name,
            "size": file_size,
            "face_count": face_count,
            "status": status,
            "error": error_msg,
            "url": f"/api/references/file/{f.name}"
        })

    return {"references": results, "active": len(results) > 0}


@app.post("/api/references/upload")
async def upload_reference(file: UploadFile = File(...)):
    """Upload a new face reference photo to me_references/."""
    ref_dir = Path("me_references")
    ref_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename).suffix.lower()
    if ext not in {'.jpg', '.jpeg', '.png', '.webp'}:
        raise HTTPException(status_code=400, detail="Invalid image format. Supported: JPG, PNG, WEBP")

    dest_path = ref_dir / file.filename
    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return {"status": "success", "filename": file.filename}


@app.delete("/api/references/{filename}")
def delete_reference(filename: str):
    """Deletes a reference file from me_references/."""
    ref_dir = Path("me_references")
    target = ref_dir / filename
    if target.exists():
        target.unlink()
        return {"status": "success", "message": f"Deleted {filename}"}
    raise HTTPException(status_code=404, detail="File not found")


@app.get("/api/references/file/{filename}")
def get_reference_file(filename: str):
    """Streams a reference photo file to the browser."""
    ref_dir = Path("me_references").resolve()
    target = (ref_dir / filename).resolve()

    if not str(target).startswith(str(ref_dir)) or not target.exists():
        raise HTTPException(status_code=404, detail="Reference image not found")

    return FileResponse(target)


# --- Scanning & Processing Endpoints ---

def run_scan_pipeline(scan_dir_str: str, threshold: int, duration_tolerance: float, dry_run: bool):
    """Background thread function executing the full BestTake scan pipeline."""
    global scan_state
    scan_state["running"] = True
    scan_state["current"] = 0
    scan_state["total"] = 0
    scan_state["message"] = "Initializing scan pipeline..."
    scan_state["summary"] = None

    try:
        scan_path = Path(scan_dir_str).resolve()
        output_path = scan_path / "_best_take_output"
        scan_state["scan_dir"] = str(scan_path)
        scan_state["output_dir"] = str(output_path)

        # Database Setup
        script_dir = Path(__file__).resolve().parent.parent
        db_path = script_dir / "media_cache.db"
        db_handler = DatabaseHandler(db_path)

        # Load reference face encodings
        known_encodings = []
        me_ref_path = Path("me_references")
        if me_ref_path.exists():
            import face_recognition
            ref_exts = {'.jpg', '.jpeg', '.png', '.webp'}
            for ref_file in me_ref_path.iterdir():
                if ref_file.suffix.lower() in ref_exts:
                    try:
                        img = face_recognition.load_image_file(str(ref_file))
                        locs = face_recognition.face_locations(img)
                        if len(locs) == 1:
                            encs = face_recognition.face_encodings(img, locs)
                            if encs:
                                known_encodings.append(encs[0])
                    except Exception:
                        pass

        # Load DB cache
        cached_metadata = db_handler.get_cached_metadata()

        # Collect files
        scan_state["message"] = "Scanning file directory..."
        IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
        VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.mov', '.avi'}

        files_to_process = []
        valid_scanned_metadata = []
        visited_paths = set()
        failed_files = []

        for root, dirs, files in os.walk(scan_path):
            current_dir = Path(root).resolve()
            if output_path in current_dir.parents or current_dir == output_path:
                continue

            for filename in files:
                if filename.startswith('.'):
                    continue

                file_path = current_dir / filename
                ext = file_path.suffix.lower()
                file_type = 'image' if ext in IMAGE_EXTENSIONS else ('video' if ext in VIDEO_EXTENSIONS else None)
                if not file_type:
                    continue

                visited_paths.add(str(file_path))
                try:
                    file_size = file_path.stat().st_size
                    mtime = file_path.stat().st_mtime
                except OSError:
                    failed_files.append(str(file_path))
                    continue

                cached = cached_metadata.get(str(file_path))
                if cached and cached.file_size == file_size and cached.modified_time == mtime:
                    valid_scanned_metadata.append(cached)
                else:
                    files_to_process.append((str(file_path), file_type))

        scan_state["total"] = len(files_to_process)
        scan_state["message"] = f"Processing {len(files_to_process)} media files..."

        # Process new files using multiprocessing pool
        processed_results = []
        if files_to_process:
            import multiprocessing
            num_cores = multiprocessing.cpu_count()
            with multiprocessing.Pool(
                processes=num_cores,
                initializer=init_worker,
                initargs=(known_encodings,)
            ) as pool:
                for idx, res in enumerate(pool.imap_unordered(process_media_worker, files_to_process), 1):
                    scan_state["current"] = idx
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
                    else:
                        failed_files.append(res['file_path'])

            if processed_results:
                db_handler.save_metadata_batch(processed_results)

        # Clustering & Archiving
        scan_state["message"] = "Clustering & Resolving Winners..."
        duplicate_clusters = MediaClusterer.cluster(
            valid_scanned_metadata,
            threshold=threshold,
            duration_tolerance=duration_tolerance
        )

        archiver = FileArchiver(scan_path, output_path, dry_run=dry_run)
        for failed_path in failed_files:
            archiver.move_failed_file(failed_path)

        all_winners = []
        all_losers = []
        resolved_groups = []
        space_saved = 0

        for group_idx, cluster in enumerate(duplicate_clusters, 1):
            winner, losers = QualityEvaluator.resolve_cluster(cluster)
            all_winners.append(winner)
            all_losers.extend(losers)
            space_saved += sum(l.file_size for l in losers)
            archiver.archive_duplicate_group(group_idx, winner, losers)
            resolved_groups.append((winner, losers))

        grouped_paths = {m.file_path for cluster in duplicate_clusters for m in cluster}
        failed_set = set(failed_files)
        singletons = [m for m in valid_scanned_metadata if m.file_path not in grouped_paths and m.file_path not in failed_set]

        for singleton in singletons:
            archiver.create_keep_symlink(singleton)
        for winner in all_winners:
            archiver.create_keep_symlink(winner)

        # Complete
        scan_state["running"] = False
        scan_state["message"] = "Scan completed successfully!"
        scan_state["summary"] = {
            "total_scanned": len(visited_paths),
            "total_kept": len(singletons) + len(all_winners),
            "keepers_me": len([m for m in singletons + all_winners if m.me_present == 1]),
            "keepers_others": len([m for m in singletons + all_winners if m.me_present == 2]),
            "keepers_scenery": len([m for m in singletons + all_winners if m.me_present == 0]),
            "duplicates": len(all_losers),
            "failures": len(failed_files),
            "space_saved_mb": round(space_saved / (1024 * 1024), 2),
            "dry_run": dry_run
        }

    except Exception as e:
        logger.error(f"Scan pipeline failed: {e}", exc_info=True)
        scan_state["running"] = False
        scan_state["message"] = f"Error: {str(e)}"


@app.post("/api/scan")
def start_scan(req: ScanRequest):
    """Starts a scan pipeline execution in a background thread."""
    global scan_state
    if scan_state["running"]:
        raise HTTPException(status_code=400, detail="A scan is already in progress.")

    target = Path(req.scan_dir).resolve()
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="Target scan directory does not exist.")

    thread = Thread(
        target=run_scan_pipeline,
        args=(str(target), req.threshold, req.duration_tolerance, req.dry_run)
    )
    thread.daemon = True
    thread.start()

    return {"status": "started", "message": f"Scan started on {target}"}


@app.get("/api/scan/progress")
def get_scan_progress():
    """Returns real-time scan progress state."""
    return scan_state


# --- Results & Local Media Serving Endpoints ---

@app.get("/api/results")
def get_results(output_dir: Optional[str] = None):
    """Reads output directory structure and returns categorized media for gallery display."""
    target_output = output_dir or scan_state.get("output_dir")
    if not target_output:
        raise HTTPException(status_code=400, detail="No scan output directory specified.")

    out_path = Path(target_output).resolve()
    if not out_path.exists():
        raise HTTPException(status_code=404, detail="Output directory does not exist.")

    def scan_folder(folder_path: Path):
        items = []
        if folder_path.exists():
            for root, dirs, files in os.walk(folder_path):
                for f in files:
                    if f.startswith('.'):
                        continue
                    file_p = Path(root) / f
                    ext = file_p.suffix.lower()
                    if ext in {'.jpg', '.jpeg', '.png', '.webp', '.mp4', '.mkv', '.mov', '.avi'}:
                        items.append({
                            "filename": f,
                            "path": str(file_p),
                            "media_type": "video" if ext in {'.mp4', '.mkv', '.mov', '.avi'} else "image",
                            "size": file_p.stat().st_size,
                            "media_url": f"/api/media/{file_p}"
                        })
        return items

    me_items = scan_folder(out_path / "keep" / "me")
    others_items = scan_folder(out_path / "keep" / "others")
    scenery_items = scan_folder(out_path / "keep" / "scenery")
    failed_items = scan_folder(out_path / "failed")

    # Scan duplicates groups
    dup_groups = []
    dup_dir = out_path / "duplicates"
    if dup_dir.exists():
        for group_folder in sorted(dup_dir.glob("group_*")):
            if group_folder.is_dir():
                losers = []
                winner_ref = None
                info_text = ""
                for f in group_folder.iterdir():
                    if f.name == "group_info.md":
                        with open(f, "r") as info_f:
                            info_text = info_f.read()
                    elif f.name.startswith("winner_ref_"):
                        winner_ref = {
                            "filename": f.name.replace("winner_ref_", ""),
                            "path": str(f.resolve()),
                            "media_url": f"/api/media/{f.resolve()}"
                        }
                    elif not f.name.startswith('.'):
                        losers.append({
                            "filename": f.name,
                            "path": str(f),
                            "size": f.stat().st_size,
                            "media_url": f"/api/media/{f}"
                        })
                dup_groups.append({
                    "group_name": group_folder.name,
                    "winner": winner_ref,
                    "losers": losers,
                    "info": info_text
                })

    return {
        "output_dir": str(out_path),
        "keep_me": me_items,
        "keep_others": others_items,
        "keep_scenery": scenery_items,
        "duplicates": dup_groups,
        "failed": failed_items,
        "summary": scan_state.get("summary")
    }


@app.get("/api/media/{file_path:path}")
def stream_media(file_path: str):
    """Safely streams local image or video files to the browser for UI thumbnails and previews."""
    target = Path("/" + file_path.lstrip("/")).resolve()
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Media file not found")

    ext = target.suffix.lower()
    media_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.webp': 'image/webp',
        '.mp4': 'video/mp4',
        '.mov': 'video/quicktime',
        '.mkv': 'video/x-matroska',
        '.avi': 'video/x-msvideo'
    }
    content_type = media_types.get(ext, 'application/octet-stream')
    return FileResponse(target, media_type=content_type)
