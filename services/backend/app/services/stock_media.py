"""Stock media service for fetching B-roll video clips from Pexels API."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)

PEXELS_VIDEO_SEARCH_URL = "https://api.pexels.com/videos/search"
CACHE_TTL_SECONDS = 86400  # 24 hours


class StockMediaService:
    """Fetch stock video clips from Pexels API."""

    def __init__(self, api_key: str, cache_dir: Path | None = None):
        self.api_key = api_key
        self.cache_dir = cache_dir
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self, query: str, orientation: str) -> Path | None:
        """Get cache file path for a search query."""
        if not self.cache_dir:
            return None
        cache_key = hashlib.md5(f"{query}:{orientation}".encode()).hexdigest()
        return self.cache_dir / f"pexels_cache_{cache_key}.json"

    def _load_from_cache(self, query: str, orientation: str) -> list[dict] | None:
        """Load cached search results if still valid."""
        cache_path = self._get_cache_path(query, orientation)
        if not cache_path or not cache_path.exists():
            return None

        try:
            data = json.loads(cache_path.read_text())
            if time.time() - data.get("timestamp", 0) < CACHE_TTL_SECONDS:
                logger.debug("Cache hit for query: %s", query)
                return data.get("results", [])
        except Exception:
            pass
        return None

    def _save_to_cache(self, query: str, orientation: str, results: list[dict]) -> None:
        """Save search results to cache."""
        cache_path = self._get_cache_path(query, orientation)
        if not cache_path:
            return

        try:
            cache_path.write_text(json.dumps({
                "timestamp": time.time(),
                "query": query,
                "orientation": orientation,
                "results": results,
            }))
        except Exception as e:
            logger.warning("Failed to save cache: %s", e)

    def search_videos(
        self,
        query: str,
        orientation: str = "landscape",
        min_duration: int = 3,
        max_duration: int = 15,
        per_page: int = 5,
    ) -> list[dict]:
        """Search Pexels for stock video clips.

        Args:
            query: Search query string
            orientation: 'landscape', 'portrait', or 'square'
            min_duration: Minimum clip duration in seconds
            max_duration: Maximum clip duration in seconds
            per_page: Number of results to fetch

        Returns:
            List of video metadata dicts with keys:
            - id: Pexels video ID
            - url: Direct download URL for the video file
            - duration: Video duration in seconds
            - width: Video width in pixels
            - height: Video height in pixels
        """
        # Check cache first
        cached = self._load_from_cache(query, orientation)
        if cached is not None:
            return cached

        headers = {"Authorization": self.api_key}
        params = {
            "query": query,
            "orientation": orientation,
            "per_page": per_page,
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(PEXELS_VIDEO_SEARCH_URL, headers=headers, params=params)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as e:
            logger.error("Pexels API error: %s", e.response.status_code)
            return []
        except Exception as e:
            logger.error("Pexels API request failed: %s", e)
            return []

        results: list[dict] = []
        total_videos = len(data.get("videos", []))
        filtered_count = 0
        for video in data.get("videos", []):
            duration = video.get("duration", 0)
            if duration < min_duration or duration > max_duration:
                filtered_count += 1
                continue

            # Find the best quality video file (prefer HD)
            video_files = video.get("video_files", [])
            best_file = None
            for vf in video_files:
                if vf.get("quality") == "hd" and vf.get("file_type") == "video/mp4":
                    best_file = vf
                    break
            if not best_file and video_files:
                # Fallback to first available MP4
                for vf in video_files:
                    if vf.get("file_type") == "video/mp4":
                        best_file = vf
                        break

            if best_file:
                results.append({
                    "id": video.get("id"),
                    "url": best_file.get("link"),
                    "duration": duration,
                    "width": best_file.get("width", 1920),
                    "height": best_file.get("height", 1080),
                })

        # Cache the results
        self._save_to_cache(query, orientation, results)

        if filtered_count > 0 and not results:
            logger.warning(
                "Pexels search '%s': all %d results filtered by duration (%d-%ds) — consider widening range",
                query, total_videos, min_duration, max_duration,
            )
        logger.info("Pexels search '%s' returned %d clips (%d/%d filtered by duration)", query, len(results), filtered_count, total_videos)
        return results

    def download_clip(self, video_url: str, output_path: Path) -> Path | None:
        """Download a video clip to local filesystem.

        Args:
            video_url: Direct URL to the video file
            output_path: Local path to save the video

        Returns:
            Path to downloaded file, or None if download failed
        """
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                with client.stream("GET", video_url) as response:
                    response.raise_for_status()
                    with open(output_path, "wb") as f:
                        for chunk in response.iter_bytes(chunk_size=8192):
                            f.write(chunk)
            logger.info("Downloaded clip to %s", output_path)
            return output_path
        except Exception as e:
            logger.error("Failed to download clip: %s", e)
            return None


def generate_search_queries(
    script_lines: list[str],
    product_description: str,
    bedrock_client,
    model_id: str,
    use_mock: bool = False,
) -> list[str]:
    """Use LLM to generate Pexels search queries for each scene.

    Args:
        script_lines: List of script lines (one per scene)
        product_description: Product description for context
        bedrock_client: Boto3 Bedrock runtime client
        model_id: Bedrock model ID to use
        use_mock: If True, return mock queries

    Returns:
        List of search queries (one per script line)
    """
    if use_mock:
        # Return generic mock queries based on common B-roll themes
        mock_queries = [
            "person using product happy",
            "lifestyle modern home",
            "hands unboxing package",
            "satisfied customer smiling",
            "professional workspace",
            "people shopping online",
        ]
        return [mock_queries[i % len(mock_queries)] for i in range(len(script_lines))]

    # Build prompt for LLM
    prompt = f"""You are a video producer selecting B-roll footage for a product marketing video.

Product: {product_description[:500]}

For each scene's narration below, generate a short search query (3-5 words) to find relevant stock footage on Pexels. The footage should complement the narration and show lifestyle/usage scenarios.

Rules:
- Keep queries generic enough to find results (avoid brand names)
- Focus on actions, emotions, and settings
- Use simple, common search terms
- Return ONLY the search queries, one per line, in the same order as the scenes

Scenes:
"""
    for i, line in enumerate(script_lines):
        prompt += f"{i+1}. {line}\n"

    prompt += "\nSearch queries (one per line):"

    try:
        response = bedrock_client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 500, "temperature": 0.3},
        )

        response_text = response["output"]["message"]["content"][0]["text"]
        queries = [q.strip() for q in response_text.strip().split("\n") if q.strip()]

        # Ensure we have one query per script line
        while len(queries) < len(script_lines):
            queries.append("lifestyle product usage")

        return queries[:len(script_lines)]

    except Exception as e:
        logger.error("Failed to generate search queries: %s", e)
        # Fallback to generic queries
        return ["lifestyle product usage"] * len(script_lines)


def get_orientation_for_aspect_ratio(aspect_ratio: str) -> str:
    """Map aspect ratio to Pexels orientation parameter."""
    mapping = {
        "16:9": "landscape",
        "1:1": "square",
        "9:16": "portrait",
    }
    return mapping.get(aspect_ratio, "landscape")
