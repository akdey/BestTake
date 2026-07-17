from typing import List, Tuple
from besttake.models import MediaMetadata

class QualityEvaluator:
    """Determines the winner of each duplicate cluster based on hierarchy logic with face filtering override."""
    @staticmethod
    def image_quality_key(meta: MediaMetadata) -> Tuple[int, float, int, float]:
        resolution = (meta.width or 0) * (meta.height or 0)
        sharpness = meta.sharpness or 0.0
        file_size = meta.file_size or 0
        # Older modified_time is prioritized as original. Negating it for descending sort.
        mtime_neg = -meta.modified_time if meta.modified_time else 0.0
        return (resolution, sharpness, file_size, mtime_neg)

    @staticmethod
    def video_quality_key(meta: MediaMetadata) -> Tuple[int, int, float]:
        resolution = (meta.width or 0) * (meta.height or 0)
        file_size = meta.file_size or 0
        mtime_neg = -meta.modified_time if meta.modified_time else 0.0
        return (resolution, file_size, mtime_neg)

    @classmethod
    def resolve_cluster(cls, cluster: List[MediaMetadata]) -> Tuple[MediaMetadata, List[MediaMetadata]]:
        """Returns (Winner, List of Losers) prioritizing files with me_present = 1."""
        is_video = any(m.file_type == 'video' for m in cluster)
        
        # 1. Split cluster by me_present
        me_present_group = [m for m in cluster if m.me_present == 1]
        
        # 2. Override: if user is present in any duplicate, ignore all files without the user
        if me_present_group:
            candidates = me_present_group
        else:
            candidates = cluster

        if is_video:
            sorted_candidates = sorted(candidates, key=cls.video_quality_key, reverse=True)
        else:
            sorted_candidates = sorted(candidates, key=cls.image_quality_key, reverse=True)
            
        winner = sorted_candidates[0]
        losers = [m for m in cluster if m.file_path != winner.file_path]
        return winner, losers
        
