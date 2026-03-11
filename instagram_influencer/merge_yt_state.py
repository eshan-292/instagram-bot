#!/usr/bin/env python3
"""Merge YouTube fields from remote content_queue.json into local copy.

Prevents race condition where IG workflow overwrites youtube_video_id
set by a concurrent YT workflow.

Usage: python merge_yt_state.py <persona>
"""

import json
import subprocess
import sys


YT_FIELDS = [
    "youtube_video_id",
    "youtube_posted_at",
    "youtube_pin_comment_id",
    "yt_status",
]


def merge(persona: str) -> None:
    local_path = f"instagram_influencer/data/{persona}/content_queue.json"

    # Read local queue
    try:
        with open(local_path) as f:
            local = json.load(f)
    except Exception:
        return  # No local file — nothing to merge

    # Fetch remote version
    try:
        remote_raw = subprocess.check_output(
            ["git", "show", f"origin/main:{local_path}"],
            stderr=subprocess.DEVNULL,
        )
        remote = json.loads(remote_raw)
    except Exception:
        return  # No remote file or git error — skip merge

    # Build remote lookup by post ID
    remote_by_id = {p.get("id"): p for p in remote.get("posts", [])}

    merged = 0
    for post in local.get("posts", []):
        pid = post.get("id")
        if not pid or pid not in remote_by_id:
            continue
        remote_post = remote_by_id[pid]
        for field in YT_FIELDS:
            remote_val = remote_post.get(field)
            local_val = post.get(field)
            # If remote has a value and local doesn't, copy it
            if remote_val and not local_val:
                post[field] = remote_val
                merged += 1

    if merged:
        with open(local_path, "w") as f:
            json.dump(local, f, indent=2, ensure_ascii=False)
        print(f"Merged {merged} YouTube field(s) from remote for {persona}")


if __name__ == "__main__":
    persona = sys.argv[1] if len(sys.argv) > 1 else "maya"
    merge(persona)
