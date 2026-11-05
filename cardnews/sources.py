"""외신 RSS + (선택) Reddit 에서 헤드라인을 모은다."""
import calendar
import html
import re
import time

import feedparser
import requests

from .config import USER_AGENT, env


def _clean(text: str, limit: int = 240) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    return text[:limit]


def fetch_feeds(cfg: dict) -> list[dict]:
    max_age = cfg.get("max_age_hours", 30) * 3600
    now = time.time()
    items = []
    for feed in cfg["feeds"]:
        try:
            resp = requests.get(feed["url"], headers={"User-Agent": USER_AGENT}, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[sources] {feed['name']} 실패: {e}")
            continue
        parsed = feedparser.parse(resp.content)
        for entry in parsed.entries:
            ts = entry.get("published_parsed") or entry.get("updated_parsed")
            published = calendar.timegm(ts) if ts else now
            if now - published > max_age:
                continue
            items.append({
                "source": feed["name"],
                "title": _clean(entry.get("title", ""), 200),
                "summary": _clean(entry.get("summary", "")),
                "link": entry.get("link", ""),
                "published": int(published),
            })
    return items


def fetch_reddit(cfg: dict) -> list[dict]:
    client_id, secret = env("REDDIT_CLIENT_ID"), env("REDDIT_CLIENT_SECRET")
    if not (client_id and secret):
        return []
    headers = {"User-Agent": USER_AGENT}
    try:
        token = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(client_id, secret),
            data={"grant_type": "client_credentials"},
            headers=headers,
            timeout=20,
        ).json()["access_token"]
    except (requests.RequestException, KeyError) as e:
        print(f"[sources] Reddit 인증 실패: {e}")
        return []

    items = []
    headers["Authorization"] = f"bearer {token}"
    for sub in cfg.get("reddit", {}).get("subreddits", []):
        try:
            resp = requests.get(
                f"https://oauth.reddit.com/r/{sub}/top",
                params={"t": "day", "limit": cfg["reddit"].get("limit", 25)},
                headers=headers,
                timeout=20,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[sources] r/{sub} 실패: {e}")
            continue
        for child in resp.json()["data"]["children"]:
            post = child["data"]
            if post.get("is_self") or post.get("over_18"):
                continue
            items.append({
                "source": f"Reddit r/{sub}",
                "title": _clean(post["title"], 200),
                "summary": "",
                "link": post["url"],
                "published": int(post["created_utc"]),
                "score": post["score"],
                "comments": post["num_comments"],
            })
    return items


def collect(cfg: dict, posted_links: set[str]) -> list[dict]:
    items = fetch_feeds(cfg) + fetch_reddit(cfg)
    items = [it for it in items if it["link"] and it["link"] not in posted_links]
    for i, it in enumerate(items):
        it["i"] = i
    print(f"[sources] 헤드라인 {len(items)}개 수집")
    return items
