"""
Beehiiv API client for the JoCo Weekend Newsletter.

API docs: https://developers.beehiiv.com/api-reference/posts/create
Base URL: https://api.beehiiv.com/v2
Auth:     Bearer token in Authorization header

Environment variables required:
  BEEHIIV_API_KEY       — your API key (starts with a long alphanumeric string)
  BEEHIIV_PUBLICATION_ID — your publication ID (format: pub_xxxxxxxx-xxxx-...)

Usage:
  from beehiiv import BeehiivClient
  client = BeehiivClient()
  result = client.create_post(title="...", html="...", scheduled_at=..., draft=True)
"""

from __future__ import annotations

import os
import logging
from datetime import datetime
from typing import Optional
import requests
import pytz

logger = logging.getLogger("Beehiiv")

BASE_URL = "https://api.beehiiv.com/v2"
CENTRAL  = pytz.timezone("America/Chicago")


class BeehiivClient:

    def __init__(
        self,
        api_key: Optional[str] = None,
        publication_id: Optional[str] = None,
    ):
        self.api_key        = api_key        or os.environ.get("BEEHIIV_API_KEY", "")
        self.publication_id = publication_id or os.environ.get("BEEHIIV_PUBLICATION_ID", "")

        if not self.api_key:
            raise ValueError(
                "BEEHIIV_API_KEY not set. "
                "Export it in your shell: export BEEHIIV_API_KEY='your_key'"
            )
        if not self.publication_id:
            raise ValueError(
                "BEEHIIV_PUBLICATION_ID not set. "
                "Export it in your shell: export BEEHIIV_PUBLICATION_ID='pub_...'"
            )

        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    # ── Public API ────────────────────────────────────────────────────────────

    def create_post(
        self,
        title: str,
        html: str,
        subtitle: Optional[str] = None,
        scheduled_at: Optional[datetime] = None,
        draft: bool = True,
        thumbnail_url: Optional[str] = None,
        content_tags: Optional[list[str]] = None,
    ) -> dict:
        """
        Create a newsletter post in Beehiiv.

        Args:
            title:         Subject line / post title.
            html:          Full HTML body (inline styles only — Beehiiv strips <style> tags).
            subtitle:      Optional preview text shown in email clients.
            scheduled_at:  When to send. None = immediate (if status=confirmed).
            draft:         True = save as draft for review. False = schedule/send immediately.
            thumbnail_url: Optional hero image URL for the post thumbnail.
            content_tags:  Optional list of tags, e.g. ["weekend", "events"].

        Returns:
            The Beehiiv API response dict.

        Raises:
            requests.HTTPError on non-2xx responses.
        """
        status = "draft" if draft else "confirmed"

        payload: dict = {
            "title": title,
            "body_content": html,
            "status": status,
        }

        if subtitle:
            payload["subtitle"] = subtitle

        if scheduled_at:
            # Beehiiv expects ISO 8601 UTC
            if scheduled_at.tzinfo is None:
                scheduled_at = CENTRAL.localize(scheduled_at)
            payload["scheduled_at"] = scheduled_at.astimezone(pytz.utc).isoformat()

        if thumbnail_url:
            payload["thumbnail_image_url"] = thumbnail_url

        if content_tags:
            payload["content_tags"] = content_tags

        url = f"{BASE_URL}/publications/{self.publication_id}/posts"
        logger.info(f"POST {url}  status={status}  title={title!r}")

        resp = self._session.post(url, json=payload, timeout=20)

        if not resp.ok:
            logger.error(f"Beehiiv API error {resp.status_code}: {resp.text}")
            resp.raise_for_status()

        data = resp.json()
        post = data.get("data", data)
        post_id  = post.get("id", "unknown")
        post_url = post.get("web_url") or post.get("url") or ""

        logger.info(f"✅  Post created: id={post_id}  url={post_url}")
        return data

    def list_posts(self, limit: int = 5) -> list[dict]:
        """Fetch the most recent posts — useful for confirming the last send."""
        url = f"{BASE_URL}/publications/{self.publication_id}/posts"
        resp = self._session.get(url, params={"limit": limit}, timeout=15)
        resp.raise_for_status()
        return resp.json().get("data", [])

    def get_publication(self) -> dict:
        """Fetch publication metadata — useful for confirming the ID is correct."""
        url = f"{BASE_URL}/publications/{self.publication_id}"
        resp = self._session.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json().get("data", {})
