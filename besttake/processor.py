import os
import hashlib
import logging
from typing import Tuple, List

from PIL import Image, ImageOps
import numpy as np

logger = logging.getLogger("BestTake")

# Global reference encodings and config cached inside the process worker memory space
known_encodings: List = []
face_tolerance_val: float = 0.48
min_review_sharpness: float = 50.0

def init_worker(encodings: List, tolerance: float = 0.48, review_sharpness: float = 50.0):
    """Initializer for Pool workers to load known face encodings and config settings."""
    global known_encodings, face_tolerance_val, min_review_sharpness
    known_encodings = encodings
    face_tolerance_val = tolerance
    min_review_sharpness = review_sharpness


def compute_md5(file_path: str) -> str:
    """Computes MD5 hash in chunks to optimize memory usage."""
    hasher = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def process_media_worker(args: Tuple[str, str]) -> dict:
    """
    Multiprocessing worker function.
    Processes a single file and extracts metadata/hashes, sharpness, face status code.
    Status Codes for me_present:
    1: User Face Present
    2: Others' Faces Present
    0: Scenery (No Faces)
    3: Review (Low Sharpness / Blurry)
    """
    file_path, file_type = args
    try:
        file_size = os.path.getsize(file_path)
        modified_time = os.path.getmtime(file_path)
        md5_hash = compute_md5(file_path)
        me_present = 0

        global known_encodings, face_tolerance_val, min_review_sharpness
        tol = face_tolerance_val if 'face_tolerance_val' in globals() else 0.48
        min_sharp = min_review_sharpness if 'min_review_sharpness' in globals() else 50.0

        if file_type == 'image':
            import imagehash
            import cv2

            # 1. Dimensions and Perceptual Hashing with EXIF Transpose
            with Image.open(file_path) as raw_img:
                img = ImageOps.exif_transpose(raw_img)
                width, height = img.size
                phash_val = str(imagehash.phash(img))

            # 2. OpenCV Laplacian Sharpness
            cv_img = cv2.imread(file_path, cv2.IMREAD_GRAYSCALE)
            if cv_img is None:
                raise ValueError("OpenCV failed to decode image")
            sharpness = float(cv2.Laplacian(cv_img, cv2.CV_64F).var())

            # 3. Face recognition with EXIF Transpose & 1x upsampling for higher precision
            if known_encodings:
                try:
                    import face_recognition
                    raw_arr = face_recognition.load_image_file(file_path)
                    pil_face_img = Image.fromarray(raw_arr)
                    pil_face_img = ImageOps.exif_transpose(pil_face_img)
                    face_arr = np.array(pil_face_img.convert('RGB'))

                    face_locs = face_recognition.face_locations(face_arr, number_of_times_to_upsample=1)
                    if face_locs:
                        me_present = 2
                        face_encs = face_recognition.face_encodings(face_arr, face_locs)
                        for enc in face_encs:
                            matches = face_recognition.compare_faces(known_encodings, enc, tolerance=tol)
                            if any(matches):
                                me_present = 1
                                break
                    else:
                        me_present = 0
                except Exception as fe:
                    logger.debug(f"Face filtering failed for image {file_path}: {fe}")

            # If not user's face, check for low sharpness/blurry review
            if me_present != 1 and sharpness < min_sharp:
                me_present = 3

            return {
                'status': 'success',
                'file_path': file_path,
                'file_type': 'image',
                'file_size': file_size,
                'modified_time': modified_time,
                'md5_hash': md5_hash,
                'perceptual_hash': phash_val,
                'duration': None,
                'width': width,
                'height': height,
                'sharpness': sharpness,
                'me_present': me_present
            }

        elif file_type == 'video':
            import cv2
            import imagehash

            cap = cv2.VideoCapture(file_path)
            if not cap.isOpened():
                raise ValueError("OpenCV failed to open video file")

            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            if fps <= 0 or frame_count <= 0:
                cap.release()
                raise ValueError(f"Invalid video structure: fps={fps}, frame_count={frame_count}")

            duration = frame_count / fps

            marks = [0.1, 0.3, 0.5, 0.7, 0.9]
            frame_indices = [int(m * frame_count) for m in marks]
            frame_indices = [max(0, min(idx, frame_count - 1)) for idx in frame_indices]

            hashes = []
            for idx in frame_indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ret, frame = cap.read()
                if not ret:
                    hashes.append("0000000000000000")
                    continue
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(frame_rgb)
                hashes.append(str(imagehash.phash(pil_img)))

            if known_encodings:
                try:
                    import face_recognition
                    step = int(2.0 * fps)
                    if step <= 0:
                        step = 1

                    any_face_detected = False
                    frame_idx = 0
                    while frame_idx < frame_count:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                        ret, frame = cap.read()
                        if not ret:
                            frame_idx += step
                            continue

                        h, w = frame.shape[:2]
                        resized_frame = cv2.resize(frame, (int(w * 0.5), int(h * 0.5)))
                        rgb_frame = cv2.cvtColor(resized_frame, cv2.COLOR_BGR2RGB)

                        face_locs = face_recognition.face_locations(rgb_frame, number_of_times_to_upsample=1)
                        if face_locs:
                            any_face_detected = True
                            face_encs = face_recognition.face_encodings(rgb_frame, face_locs)
                            for enc in face_encs:
                                matches = face_recognition.compare_faces(known_encodings, enc, tolerance=tol)
                                if any(matches):
                                    me_present = 1
                                    break
                        
                        if me_present == 1:
                            break
                        frame_idx += step

                    if me_present != 1:
                        me_present = 2 if any_face_detected else 0
                except Exception as fe:
                    logger.debug(f"Face filtering failed for video {file_path}: {fe}")

            cap.release()
            perceptual_hash_str = ",".join(hashes)

            return {
                'status': 'success',
                'file_path': file_path,
                'file_type': 'video',
                'file_size': file_size,
                'modified_time': modified_time,
                'md5_hash': md5_hash,
                'perceptual_hash': perceptual_hash_str,
                'duration': duration,
                'width': width,
                'height': height,
                'sharpness': None,
                'me_present': me_present
            }
        else:
            raise ValueError(f"Unsupported file type: {file_type}")

    except Exception as e:
        return {
            'status': 'failed',
            'file_path': file_path,
            'error': str(e)
        }
