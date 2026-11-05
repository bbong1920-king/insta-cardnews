"""게시 이력, 승인 대기 목록, 텔레그램 offset 을 data/state.json 에 저장한다.
GitHub Actions 에서는 매 실행 후 이 파일을 커밋해서 다음 실행으로 넘긴다."""
import json
import time

from .config import DATA_DIR

STATE_FILE = DATA_DIR / "state.json"


def load() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"tg_offset": 0, "pending": {}, "posted": []}


def save(state: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    state["posted"] = state["posted"][-300:]
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def posted_links(state: dict) -> set[str]:
    links = set()
    for p in state["posted"] + list(state["pending"].values()):
        links.update(p.get("links", []))
    return links


def recent_titles(state: dict, n: int = 40) -> list[str]:
    entries = state["posted"][-n:] + list(state["pending"].values())
    return [p["story"] for p in entries if p.get("story")]


def mark_posted(state: dict, card_id: str, result: dict) -> None:
    card = state["pending"].pop(card_id)
    card.update(result, posted_at=int(time.time()))
    state["posted"].append(card)
