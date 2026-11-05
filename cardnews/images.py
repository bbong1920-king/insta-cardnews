"""대표 이미지 확보: Wikimedia Commons 자유 라이선스 사진 → 없으면 AI 생성 → 그것도 없으면 사진 없는 디자인."""
import base64
import io
import re
from pathlib import Path

import requests
from PIL import Image

from . import writer
from .config import USER_AGENT, env

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
# 상업적 이용·변경이 허용되는 라이선스만 (NC/ND 제외)
OK_LICENSE = re.compile(r"^(cc0|public domain|pd\b|pd-|cc[ -]by(-sa)?[ -]\d)", re.I)


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text or "")).strip()


def _download(url: str) -> bytes | None:
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
        return resp.content
    except requests.RequestException as e:
        print(f"[images] 다운로드 실패 {url}: {e}")
        return None


def _preview(data: bytes) -> bytes:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((512, 512))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def search_commons(query: str, min_width: int, limit: int = 6) -> list[dict]:
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap",
        "gsrnamespace": 6,
        "gsrlimit": limit,
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": 1280,
    }
    try:
        resp = requests.get(COMMONS_API, params=params, headers={"User-Agent": USER_AGENT}, timeout=20)
        pages = resp.json().get("query", {}).get("pages", {})
    except (requests.RequestException, ValueError) as e:
        print(f"[images] Commons 검색 실패 ({query}): {e}")
        return []

    results = []
    for page in sorted(pages.values(), key=lambda p: p.get("index", 0)):
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        license_name = meta.get("LicenseShortName", {}).get("value", "")
        if info.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
            continue
        if info.get("width", 0) < min_width or not OK_LICENSE.match(license_name):
            continue
        # 파노라마처럼 너무 가로로 긴 사진은 카드에 잘라 넣으면 흐려진다
        if info.get("width", 0) > 2 * info.get("height", 1):
            continue
        results.append({
            "title": page["title"].removeprefix("File:"),
            "thumb_url": info.get("thumburl") or info["url"],
            "page_url": info.get("descriptionurl", ""),
            "author": _strip_html(meta.get("Artist", {}).get("value", ""))[:60] or "작자 미상",
            "license": license_name,
        })
    return results


def from_commons(cfg: dict, card: dict) -> dict | None:
    min_width = cfg["image"].get("min_width", 900)
    seen, candidates = set(), []
    for q in card["image_queries"][:3]:
        for c in search_commons(q, min_width):
            if c["title"] in seen:
                continue
            seen.add(c["title"])
            data = _download(c["thumb_url"])
            if data:
                c["data"], c["preview"] = data, _preview(data)
                candidates.append(c)
        if len(candidates) >= 8:
            break
    if not candidates:
        return None
    idx = writer.pick_image(cfg, card, candidates[:8])
    if idx < 0:
        return None
    c = candidates[idx]
    return {
        "data": c["data"],
        "credit": f"자료사진 · {c['author']} / Wikimedia Commons ({c['license']})",
        "caption_credit": f"사진: {c['author']}, {c['license']}, via Wikimedia Commons ({c['page_url']})",
    }


def from_ai(cfg: dict, card: dict) -> dict | None:
    api_key = env("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        resp = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": cfg["image"].get("ai_model", "gpt-image-1"),
                "prompt": card["ai_image_prompt"] + " No text, no logos, no real identifiable faces.",
                "size": "1024x1536",
                "n": 1,
            },
            timeout=180,
        )
        resp.raise_for_status()
        data = base64.b64decode(resp.json()["data"][0]["b64_json"])
    except (requests.RequestException, KeyError, ValueError) as e:
        print(f"[images] AI 이미지 생성 실패: {e}")
        return None
    return {"data": data, "credit": "AI 생성 이미지", "caption_credit": "이미지: AI 생성 (실제 현장 사진 아님)"}


def get_image(cfg: dict, card: dict, out_path: Path) -> dict:
    """반환: {"path": Path|None, "credit": str, "caption_credit": str}"""
    result = None
    if cfg["image"].get("commons", True):
        result = from_commons(cfg, card)
    if result is None and cfg["image"].get("ai_fallback", True):
        result = from_ai(cfg, card)
    if result is None:
        print("[images] 사진 없이 텍스트 디자인으로 진행")
        return {"path": None, "credit": "", "caption_credit": ""}
    out_path.write_bytes(result.pop("data"))
    return {"path": out_path, **result}
