from collections import defaultdict
from typing import List, Tuple
from besttake.models import MediaMetadata

class UnionFind:
    """Disjoint Set Union structure to group duplicates recursively."""
    def __init__(self, elements: List[str]):
        self.parent = {el: el for el in elements}

    def find(self, x: str) -> str:
        orig = x
        while self.parent[x] != x:
            x = self.parent[x]
        # Path compression
        curr = orig
        while curr != x:
            nxt = self.parent[curr]
            self.parent[curr] = x
            curr = nxt
        return x

    def union(self, x: str, y: str):
        root_x = self.find(x)
        root_y = self.find(y)
        if root_x != root_y:
            self.parent[root_x] = root_y


class MediaClusterer:
    """Finds exact and similarity matches, and groups duplicates using Union-Find."""
    @staticmethod
    def cluster(
        metadata_list: List[MediaMetadata],
        threshold: int = 4,
        duration_tolerance: float = 0.1
    ) -> List[List[MediaMetadata]]:
        
        paths = [m.file_path for m in metadata_list]
        uf = UnionFind(paths)
        meta_by_path = {m.file_path: m for m in metadata_list}

        # 1. Exact Match Grouping (MD5 Hash)
        md5_groups = defaultdict(list)
        for meta in metadata_list:
            md5_groups[meta.md5_hash].append(meta.file_path)

        for hash_val, path_list in md5_groups.items():
            if len(path_list) > 1:
                first = path_list[0]
                for other in path_list[1:]:
                    uf.union(first, other)

        # Separate Images and Videos for Perceptual Hashing
        images = [m for m in metadata_list if m.file_type == 'image']
        videos = [m for m in metadata_list if m.file_type == 'video']

        # 2. Image Similarity (Hamming Distance <= threshold)
        image_hashes = []
        for img in images:
            if img.perceptual_hash:
                try:
                    image_hashes.append((img.file_path, int(img.perceptual_hash, 16)))
                except ValueError:
                    continue

        n_imgs = len(image_hashes)
        for i in range(n_imgs):
            path_i, hash_i = image_hashes[i]
            for j in range(i + 1, n_imgs):
                path_j, hash_j = image_hashes[j]
                # Optimization: Skip if they already share a cluster
                if uf.find(path_i) == uf.find(path_j):
                    continue
                diff = hash_i ^ hash_j
                if diff.bit_count() <= threshold:
                    uf.union(path_i, path_j)

        # 3. Video Similarity (Duration Match + average Hamming distance <= threshold)
        video_data = []
        for vid in videos:
            if vid.perceptual_hash and vid.duration is not None:
                try:
                    hash_ints = [int(h, 16) for h in vid.perceptual_hash.split(',')]
                    if len(hash_ints) == 5:
                        video_data.append((vid, hash_ints))
                except ValueError:
                    continue

        # Sort by duration to allow linear-window similarity matching
        video_data.sort(key=lambda x: x[0].duration)

        n_vids = len(video_data)
        for i in range(n_vids):
            vid_i, hashes_i = video_data[i]
            for j in range(i + 1, n_vids):
                vid_j, hashes_j = video_data[j]
                
                # Exit early if duration difference exceeds tolerance
                if vid_j.duration - vid_i.duration > duration_tolerance:
                    break

                if uf.find(vid_i.file_path) == uf.find(vid_j.file_path):
                    continue

                # Calculate average Hamming Distance across 5 frames
                dists = [(h_i ^ h_j).bit_count() for h_i, h_j in zip(hashes_i, hashes_j)]
                avg_dist = sum(dists) / len(dists)

                if avg_dist <= threshold:
                    uf.union(vid_i.file_path, vid_j.file_path)

        # 4. Gather clusters
        clusters_dict = defaultdict(list)
        for path in paths:
            root = uf.find(path)
            clusters_dict[root].append(meta_by_path[path])

        # Filter out clusters with only 1 file (singletons)
        duplicate_clusters = [cluster for cluster in clusters_dict.values() if len(cluster) > 1]
        return duplicate_clusters
