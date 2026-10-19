#!/usr/bin/env python3
"""Post a Markdown digest to Slack: highlights as the main message, details in its thread."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"
HIGHLIGHTS_HEADING = "## Executive Highlights"
# Slack allows 12,000 characters of markdown block text per message; leave headroom.
MAX_MESSAGE_CHARS = 11_000
DEFAULT_TITLE = "Altinn changelog digest"


def split_digest(digest: str) -> tuple[str, str, str]:
    """Return (title, highlights, details) where highlights excludes its heading."""
    lines = digest.strip().splitlines()
    title = DEFAULT_TITLE
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        lines = lines[1:]

    body = "\n".join(lines).strip()
    start = body.find(HIGHLIGHTS_HEADING)
    if start == -1:
        return title, "", body

    after_heading = start + len(HIGHLIGHTS_HEADING)
    end = body.find("\n## ", after_heading)
    if end == -1:
        end = len(body)
    highlights = body[after_heading:end].strip()
    details = (body[:start] + body[end:]).strip()
    return title, highlights, details


def chunk_markdown(text: str, limit: int = MAX_MESSAGE_CHARS) -> list[str]:
    """Split text into chunks of at most `limit` chars, preferring heading boundaries."""
    sections: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("#") and current:
            sections.append("\n".join(current))
            current = []
        current.append(line)
    if current:
        sections.append("\n".join(current))

    pieces: list[str] = []
    for section in sections:
        if len(section) <= limit:
            pieces.append(section)
            continue
        buffer = ""
        for line in section.splitlines():
            while len(line) > limit:
                if buffer:
                    pieces.append(buffer)
                    buffer = ""
                pieces.append(line[:limit])
                line = line[limit:]
            candidate = f"{buffer}\n{line}" if buffer else line
            if len(candidate) > limit:
                pieces.append(buffer)
                buffer = line
            else:
                buffer = candidate
        if buffer:
            pieces.append(buffer)

    chunks: list[str] = []
    for piece in pieces:
        piece = piece.strip("\n")
        if not piece.strip():
            continue
        if chunks and len(chunks[-1]) + 2 + len(piece) <= limit:
            chunks[-1] = f"{chunks[-1]}\n\n{piece}"
        else:
            chunks.append(piece)
    return chunks


def build_messages(digest: str, run_url: str | None = None) -> list[dict[str, Any]]:
    """Build chat.postMessage payloads (without channel/thread_ts); the first is the parent."""
    title, highlights, details = split_digest(digest)
    footer_parts = []
    if details:
        footer_parts.append("Details in thread")
    if run_url:
        footer_parts.append(f"[Workflow run]({run_url})")

    parent_text = f"# {title}"
    if highlights:
        parent_text += f"\n\n{highlights}"
    if footer_parts:
        parent_text += "\n\n_" + " · ".join(footer_parts) + "_"

    parent_chunks = chunk_markdown(parent_text)
    detail_chunks = chunk_markdown(details) if details else []
    texts = parent_chunks + detail_chunks
    total = len(texts)
    return [
        {
            "text": title if index == 0 else f"{title} ({index + 1}/{total})",
            "blocks": [{"type": "markdown", "text": text}],
            "unfurl_links": False,
            "unfurl_media": False,
        }
        for index, text in enumerate(texts)
    ]


def post_message(token: str, payload: dict[str, Any], retries: int = 3) -> dict[str, Any]:
    request = urllib.request.Request(
        SLACK_POST_MESSAGE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < retries:
                time.sleep(int(exc.headers.get("Retry-After", "1")))
                continue
            raise SystemExit(f"Slack API HTTP error {exc.code}: {exc.reason}") from exc
        if not result.get("ok"):
            raise SystemExit(f"Slack API error: {result.get('error', 'unknown')}")
        return result
    raise SystemExit("Slack API rate limit retries exhausted.")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("digest_file", type=Path, help="Markdown digest to post.")
    parser.add_argument("--run-url", help="Workflow run URL to link from the main message.")
    parser.add_argument("--dry-run", action="store_true", help="Print the payloads instead of posting.")
    args = parser.parse_args(argv[1:])

    messages = build_messages(args.digest_file.read_text(encoding="utf-8"), args.run_url)
    if args.dry_run:
        print(json.dumps(messages, indent=2, ensure_ascii=False))
        return 0

    token = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_CHANNEL_ID")
    if not token or not channel:
        print("SLACK_BOT_TOKEN and SLACK_CHANNEL_ID must be set.", file=sys.stderr)
        return 2

    parent = post_message(token, {"channel": channel, **messages[0]})
    for message in messages[1:]:
        post_message(token, {"channel": channel, "thread_ts": parent["ts"], **message})
    print(f"Posted digest to Slack in {len(messages)} message(s).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
