"""텔레그램 봇으로 미리보기를 보내고 승인 버튼 응답을 받는다."""
import json
from pathlib import Path

import requests

from .config import env


def enabled() -> bool:
    return bool(env("TELEGRAM_BOT_TOKEN") and env("TELEGRAM_CHAT_ID"))


def _call(method: str, files=None, **params):
    url = f"https://api.telegram.org/bot{env('TELEGRAM_BOT_TOKEN', required=True)}/{method}"
    resp = requests.post(url, data=params, files=files, timeout=60)
    body = resp.json()
    if not body.get("ok"):
        raise RuntimeError(f"Telegram {method} 실패: {body}")
    return body["result"]


def send_text(text: str, buttons: list[list[dict]] | None = None) -> dict:
    params = {"chat_id": env("TELEGRAM_CHAT_ID"), "text": text[:4096], "disable_web_page_preview": "true"}
    if buttons:
        params["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    return _call("sendMessage", **params)


def send_photo(path: Path, caption: str) -> dict:
    with open(path, "rb") as f:
        return _call("sendPhoto", files={"photo": f}, chat_id=env("TELEGRAM_CHAT_ID"), caption=caption[:1024])


def send_preview(entry: dict, needs_approval: bool) -> int:
    card = entry["card"]
    head = "🆕 승인 대기" if needs_approval else "🤖 자동 게시 예정"
    notes = []
    if card["sensitive"]:
        notes.append("⚠️ 민감한 뉴스로 분류됨")
    if card["fact_notes"]:
        notes.append(f"🔎 확인 필요: {card['fact_notes']}")
    send_photo(Path(entry["image_path"]), f"{head} · {entry['id']}\n{entry['story']}\n\n" + "\n".join(notes))

    buttons = None
    if needs_approval:
        buttons = [[
            {"text": "✅ 게시", "callback_data": f"approve:{entry['id']}"},
            {"text": "❌ 버리기", "callback_data": f"reject:{entry['id']}"},
        ]]
    links = "\n".join(entry["links"][:3])
    msg = send_text(
        f"[인스타 설명글]\n{entry['caption']}\n\n[스레드]\n{entry['threads_text']}\n\n[원문]\n{links}",
        buttons,
    )
    return msg["message_id"]


def get_updates(offset: int) -> list[dict]:
    return _call("getUpdates", offset=offset, timeout=0,
                 allowed_updates=json.dumps(["callback_query", "message"]))


def answer(callback_id: str, text: str) -> None:
    _call("answerCallbackQuery", callback_query_id=callback_id, text=text)


def clear_buttons(message_id: int) -> None:
    try:
        _call("editMessageReplyMarkup", chat_id=env("TELEGRAM_CHAT_ID"), message_id=message_id,
              reply_markup=json.dumps({"inline_keyboard": []}))
    except RuntimeError:
        pass
