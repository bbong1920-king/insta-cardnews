"""기사 본문 추출. 원문은 Claude 가 사실을 파악하는 데만 쓰고, 그대로 게시하지 않는다."""
import requests
import trafilatura

from .config import USER_AGENT


def fetch_text(url: str, limit: int = 8000) -> str:
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": f"Mozilla/5.0 {USER_AGENT}"},
            timeout=20,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[article] {url} 실패: {e}")
        return ""
    text = trafilatura.extract(resp.text, include_comments=False, include_tables=False) or ""
    return text[:limit]
