"""Instagram / Threads 공식 API 로 게시. 두 API 모두 이미지를 '공개 URL'에서 직접 가져간다."""
import time

import requests

from .config import env

THREADS_API = "https://graph.threads.net/v1.0"


def _check(resp: requests.Response, what: str) -> dict:
    try:
        body = resp.json()
    except ValueError:
        body = {"raw": resp.text[:500]}
    if resp.status_code >= 400 or "error" in body:
        raise RuntimeError(f"{what} 실패 ({resp.status_code}): {body}")
    return body


def _wait_ready(url: str, field: str, token: str, what: str, tries: int = 20) -> None:
    for _ in range(tries):
        body = _check(requests.get(url, params={"fields": field, "access_token": token}, timeout=30), what)
        status = body.get(field)
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"{what}: 미디어 처리 실패 ({body})")
        time.sleep(5)
    raise RuntimeError(f"{what}: 미디어 처리 시간 초과")


def instagram(cfg: dict, image_url: str, caption: str) -> str:
    token = env("IG_ACCESS_TOKEN", required=True)
    user_id = env("IG_USER_ID", required=True)
    base = f"https://graph.instagram.com/{cfg.get('ig_api_version', 'v23.0')}"

    container = _check(requests.post(f"{base}/{user_id}/media", data={
        "image_url": image_url, "caption": caption, "access_token": token,
    }, timeout=60), "인스타 컨테이너 생성")["id"]
    _wait_ready(f"{base}/{container}", "status_code", token, "인스타")

    media_id = _check(requests.post(f"{base}/{user_id}/media_publish", data={
        "creation_id": container, "access_token": token,
    }, timeout=60), "인스타 게시")["id"]
    info = _check(requests.get(f"{base}/{media_id}", params={
        "fields": "permalink", "access_token": token,
    }, timeout=30), "인스타 링크 조회")
    return info.get("permalink", media_id)


def threads(image_url: str | None, text: str) -> str:
    """image_url 이 None 이면 글만 게시한다."""
    token = env("THREADS_ACCESS_TOKEN", required=True)

    media = {"media_type": "IMAGE", "image_url": image_url} if image_url else {"media_type": "TEXT"}
    container = _check(requests.post(f"{THREADS_API}/me/threads", data={
        **media, "text": text, "access_token": token,
    }, timeout=60), "스레드 컨테이너 생성")["id"]
    _wait_ready(f"{THREADS_API}/{container}", "status", token, "스레드")

    post_id = _check(requests.post(f"{THREADS_API}/me/threads_publish", data={
        "creation_id": container, "access_token": token,
    }, timeout=60), "스레드 게시")["id"]
    info = _check(requests.get(f"{THREADS_API}/{post_id}", params={
        "fields": "permalink", "access_token": token,
    }, timeout=30), "스레드 링크 조회")
    return info.get("permalink", post_id)


def refresh_tokens(cfg: dict) -> None:
    """장기 토큰(60일)을 연장한다. 출력된 새 토큰을 GitHub Secrets 에 다시 넣으면 된다."""
    ver = cfg.get("ig_api_version", "v23.0")
    targets = [
        ("IG_ACCESS_TOKEN", f"https://graph.instagram.com/{ver}/refresh_access_token", "ig_refresh_token"),
        ("THREADS_ACCESS_TOKEN", f"{THREADS_API}/refresh_access_token", "th_refresh_token"),
    ]
    for name, url, grant in targets:
        token = env(name)
        if not token:
            continue
        body = _check(requests.get(url, params={"grant_type": grant, "access_token": token}, timeout=30), name)
        days = body.get("expires_in", 0) // 86400
        print(f"{name} (약 {days}일 유효):\n{body['access_token']}\n")
