# BestTake: Highly Optimized Duplicate Media Finder & Archiver

**BestTake** is a production-ready, high-performance command-line tool written in Python 3.10+ designed to recursively scan a directory for duplicate images and videos, identify the highest-quality file in each duplicate cluster, and safely archive the lower-quality duplicates and corrupted files into a structured review folder.

It is specifically optimized to detect and resolve variations caused by messaging apps (like **WhatsApp standard vs. HD** uploads), which downscale, compress, or strip metadata from files.

Additionally, BestTake features a **Face Filtering module** that identifies media containing a specific person (e.g., you) using local face embeddings and ensures those files are prioritized as "winners" during the duplicate resolution phase.

---

## Key Features

1. **Dual-Stage Matching**:
   - **Exact Matches**: Instant O(1) matching via file-level cryptographic MD5 byte hashes.
   - **Perceptual Similarity Matches**: Using 64-bit Perceptual Hashing (`phash`) to catch resized, recompressed, or metadata-stripped copies.
2. **Face Filtering & Winner Override**: Detects the presence of a specific user within duplicate clusters using offline face embeddings and prioritizes those photos/videos.
3. **SQLite Database Cache**: Metadata, hashes, and face detection flags are cached in `media_cache.db` using file path, size, and modification timestamp as a compound key. Re-scans are near-instantaneous.
4. **Multiprocessing Worker Pool**: Leveraging all available CPU cores to process files in parallel, with optimized memory management.
5. **Hierarchical Winner Scoring**:
   - **Images**: User Present $\rightarrow$ Resolution (Pixel count) $\rightarrow$ Edge Sharpness (Laplacian Variance) $\rightarrow$ File Size $\rightarrow$ Original Creation Time.
   - **Videos**: User Present $\rightarrow$ Resolution $\rightarrow$ File Size $\rightarrow$ Original Creation Time.
6. **Zero-Loss Reorganization**:
   - **Keep Folder (`keep/`)**: Contains symbolic links to all unique files and selected winners, preserving their original subdirectory structure.
   - **Duplicates Folder (`duplicates/`)**: Moves duplicates into subdirectories by group (`group_001`, `group_002`, etc.) with a detailed `group_info.md` summary and a symlink back to the original winner.
   - **Failed Folder (`failed/`)**: Relocates corrupted or unreadable media files out of the main directory for manual review.

---

## Installation & Setup

We recommend using the fast **`uv`** package manager to set up the environment and install dependencies.

### 1. Prerequisites (For Face Recognition)

The `face_recognition` library requires `dlib` which relies on `cmake` to compile C++ bindings.

- **macOS**: Install CMake using Homebrew:
  ```bash
  brew install cmake
  ```
- **Ubuntu/Debian**: Install compile dependencies:
  ```bash
  sudo apt update
  sudo apt install -y cmake build-essential
  ```
- **Windows**: Install Visual Studio with "C++ CMake tools for Windows" and add CMake to the system PATH.

### 2. Create a Virtual Environment

```bash
uv venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
uv pip install -r requirements.txt
```

---

## Using Face Filtering

To enable the Face Filtering module, follow these steps:

1. **Create Reference Folder**: Create a folder named `me_references/` in the root folder from which you are executing the script.
2. **Place Reference Images**: Add multiple clear photographs of yourself inside this directory. For best results, use images with varying:
   - Lighting conditions
   - Viewing angles (front, side)
   - Facial expressions (smiling, neutral)
   - Hairstyles/glasses
3. **Validation**: The tool will scan `me_references/` on startup. 
   - Reference images **must contain exactly one detectable face**.
   - Reference images with 0 or multiple faces will be skipped with a warning logged to the console.
   - The successfully loaded face embeddings are saved in memory as `known_face_encodings` for local offline comparison.
4. **Behavior**: If `me_references/` does not exist or has no valid reference images, face filtering remains disabled and related checks are skipped automatically.

---

## Video Processing Details

For video files, BestTake employs two independent sampling techniques to ensure accuracy and speed:

1. **Uniform Temporal Sampling (For Duplicates)**:
   - Frames are extracted at exactly **10%, 30%, 50%, 70%, and 90%** of the video's total duration.
   - These 5 frames are converted to perceptual hashes and combined into a deterministic fingerprint. This ensures duplicate detection is extremely robust and repeatable.
2. **Dynamic Time-Based Sampling (For Face Recognition)**:
   - The tool extracts one frame every **2 seconds** of video duration.
   - To optimize CPU execution and speed up dlib's face checks, each frame is resized to **25%** of its original resolution using OpenCV (`cv2.resize()`) before face detection.
   - If a face matching the reference profile is detected in **at least one frame**, the video is marked as `me_present = 1` and subsequent frames are skipped (early exit optimization).

---

## Winner Selection Override Matrix

Inside each duplicate cluster, the files are resolved to pick a single "Winner" according to the following tie-breaker rules:

1. **Filter Group**: If any files within the cluster contain the user (`me_present = 1`), all files where `me_present = 0` are excluded from winning.
2. **Quality Resolution**: Among the prioritized candidates, the winner is determined by:
   - **Images**: Resolution (pixel count) $\rightarrow$ Sharpness (Laplacian variance) $\rightarrow$ File Size $\rightarrow$ Original creation timestamp (oldest wins).
   - **Videos**: Resolution (pixel count) $\rightarrow$ File Size $\rightarrow$ Original creation timestamp (oldest wins).
3. **Fallback**: If no files in the cluster contain the user, the quality resolution tie-breaker is applied directly to the entire cluster.

---

## Usage

Run the tool by passing the target scan directory.

```bash
python3 best_take.py /path/to/media/directory
```

### Command Line Options

| Argument | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `scan_dir` | Position | *Required* | Directory path to recursively scan. |
| `--db` | String | `media_cache.db` | Path to the SQLite cache database. |
| `--output-dir` | String | `[scan_dir]/_best_take_output` | Directory where output subfolders are written. |
| `--threshold` | Integer | `4` | Hamming distance threshold for perceptual similarity. |
| `--duration-tolerance`| Float | `0.1` | Video duration tolerance in seconds. |
| `--dry-run` | Flag | `False` | Run scanning and reporting without moving files. |
| `--verbose` | Flag | `False` | Show detailed debug logging. |

### Running Examples

#### Dry Run Scan (Safe Investigation)
```bash
python3 best_take.py ~/Pictures --dry-run
```

#### Run with Custom Perceptual Threshold (stricter matching)
```bash
python3 best_take.py ~/Pictures --threshold 2
```

---

## Structured Output Organization

After a run, the target directory is cleaned up (losers and corrupt files are moved out), and the output directory is structured as follows:

```text
_best_take_output/
├── keep/
│   ├── me/                        # Keepers containing your face (me_present = 1)
│   │   ├── holiday/
│   │   │   └── selfie_hd.jpg      # Symlink to winner selfie
│   ├── others/                    # Keepers containing other faces but not yours (me_present = 2)
│   │   └── group_photo_hd.jpg     # Symlink to winner group photo
│   └── scenery/                   # Keepers with no faces detected (me_present = 0)
│       └── sunset.jpg             # Symlink to scenery photo
├── failed/
│   └── corrupted_image.jpg        # Moved corrupted file (failed to decode)
└── duplicates/
    ├── group_001/
    │   ├── group_info.md          # Details of comparison, sizes, MD5s, face presence
    │   ├── winner_ref_beach.jpg   # Symlink to winner for side-by-side comparison
    │   └── beach_standard.jpg     # Moved duplicate (lower quality)
    └── group_002/
        ├── group_info.md
        ├── winner_ref_video.mp4   # Symlink to high-res video
        └── video_whatsapp.mp4     # Moved duplicate (compressed video)
```

---

## Database Schema

Cached metadata is stored in `media_metadata` table:

```sql
CREATE TABLE IF NOT EXISTS media_metadata (
    file_path TEXT PRIMARY KEY,
    file_type TEXT,        -- 'image' or 'video'
    file_size INTEGER,     -- In bytes
    modified_time REAL,    -- Epoch timestamp
    md5_hash TEXT,         -- Cryptographic MD5
    perceptual_hash TEXT,  -- Image: 1 hex string. Video: 5 comma-separated hex strings.
    duration REAL,         -- For videos (NULL for images)
    width INTEGER,
    height INTEGER,
    sharpness REAL,        -- For images (NULL for videos)
    me_present INTEGER     -- 1 if user is present in media, else 0 (Default: 0)
);
```

To upgrade an existing database cache from a previous version of BestTake, the tool automatically executes an `ALTER TABLE` schema migration to add the `me_present` column.
