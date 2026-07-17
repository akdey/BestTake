from dataclasses import dataclass
from typing import Optional

@dataclass
class MediaMetadata:
    file_path: str
    file_type: str        # 'image' or 'video'
    file_size: int         # in bytes
    modified_time: float   # epoch timestamp
    md5_hash: str          # md5 checksum
    perceptual_hash: str   # image: single hex, video: comma-separated hex strings
    duration: Optional[float] = None  # video only
    width: Optional[int] = None
    height: Optional[int] = None
    sharpness: Optional[float] = None  # image only (Laplacian variance)
    me_present: int = 0   # 1 if user is present in the media, else 0

    def to_db_tuple(self) -> tuple:
        return (
            self.file_path,
            self.file_type,
            self.file_size,
            self.modified_time,
            self.md5_hash,
            self.perceptual_hash,
            self.duration,
            self.width,
            self.height,
            self.sharpness,
            self.me_present
        )

    @classmethod
    def from_db_row(cls, row: tuple) -> 'MediaMetadata':
        return cls(
            file_path=row[0],
            file_type=row[1],
            file_size=row[2],
            modified_time=row[3],
            md5_hash=row[4],
            perceptual_hash=row[5],
            duration=row[6],
            width=row[7],
            height=row[8],
            sharpness=row[9],
            me_present=row[10] if len(row) > 10 else 0
        )
