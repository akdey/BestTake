import os
import hashlib
import logging
from typing import Tuple, List

logger = logging.getLogger("BestTake")

# Global reference encodings cached inside the process memory space
known_encodings: List = []

def init_worker(encodings: List):
    """Initializer for Pool workers to load known face encodings once at startup."""
    global known_encodings
    known_encodings = encodings


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
    Processes a single file and extracts metadata/hashes and face filtering info.
    """
    file_path, file_type = args
    try:
        file_size = os.path.getsize(file_path)
        modified_time = os.path.getmtime(file_path)
        md5_hash = compute_md5(file_path)
        me_present = 0

        if file_type == 'image':
            from PIL import Image
            import imagehash
            import cv2

            # 1. Dimensions and Perceptual Hashing
            with Image.open(file_path) as img:
                width, height = img.size
                phash_val = str(imagehash.phash(img))

            # 2. OpenCV Laplacian Sharpness
            cv_img = cv2.imread(file_path, cv2.IMREAD_GRAYSCALE)
            if cv_img is None:
                raise ValueError("OpenCV failed to decode image")
            sharpness = float(cv2.Laplacian(cv_img, cv2.CV_64F).var())

            # 3. Face recognition (if Face Filtering is enabled)
            global known_encodings
            if known_encodings:
                try:
                    import face_recognition
                    face_image = face_recognition.load_image_file(file_path)
                    face_locs = face_recognition.face_locations(face_image)
                    if face_locs:
                        # At least one face is detected. Default to Others Present (2)
                        me_present = 2
                        face_encs = face_recognition.face_encodings(face_image, face_locs)
                        for enc in face_encs:
                            matches = face_recognition.compare_faces(known_encodings, enc)
                            if any(matches):
                                me_present = 1
                                break
                    else:
                        me_present = 0
                except Exception as fe:
                    logger.debug(f"Face filtering failed for image {file_path}: {fe}")

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
            from PIL import Image

            # 1. OpenCV Video Capture
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

            # 2. Keyframe Temporal Hashing (10%, 30%, 50%, 70%, 90% duration marks)
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

            # 3. Dynamic Time-Based Sampling for Face Filtering
            if known_encodings:
                try:
                    import face_recognition
                    # Extract one frame every 2 seconds
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

                        # Resize frame to 25% of original width and height to optimize speed
                        h, w = frame.shape[:2]
                        resized_frame = cv2.resize(frame, (int(w * 0.25), int(h * 0.25)))
                        rgb_frame = cv2.cvtColor(resized_frame, cv2.COLOR_BGR2RGB)

                        # Detect and encode faces
                        face_locs = face_recognition.face_locations(rgb_frame)
                        if face_locs:
                            any_face_detected = True
                            face_encs = face_recognition.face_encodings(rgb_frame, face_locs)
                            for enc in face_encs:
                                matches = face_recognition.compare_faces(known_encodings, enc)
                                if any(matches):
                                    me_present = 1
                                    break
                        
                        if me_present == 1:
                            break  # Early exit on first match
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
