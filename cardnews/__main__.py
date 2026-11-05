"""
사용법
  python -m cardnews draft          뉴스 선정 → 카드 생성 → 승인 요청 (또는 자동 게시 대기열)
  python -m cardnews poll           텔레그램 버튼 응답 처리 + 승인된 카드 게시
  python -m cardnews sample         API 키 없이 디자인 확인용 샘플 카드 만들기
  python -m cardnews chat-id        텔레그램 chat id 확인
  python -m cardnews refresh-tokens 인스타/스레드 장기 토큰 연장
"""
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import article, images, publish, render, sources, state, telegram, writer
from .config import OUTPUT_DIR, ROOT, env, load_config

KST = timezone(timedelta(hours=9))
IG_CAPTION_MAX = 2200
THREADS_MAX = 500


def build_captions(card: dict, source_names: list[str], links: list[str], image: dict) -> tuple[str, str]:
    tags = " ".join("#" + t.lstrip("#").replace(" ", "") for t in card["hashtags"][:5])
    footer = [f"📰 출처: {', '.join(source_names)}"]
    if image.get("caption_credit"):
        footer.append(f"🖼 {image['caption_credit']}")
    footer_text = "\n".join(footer) + "\n\n" + tags
    body = card["caption_body"][: IG_CAPTION_MAX - len(footer_text) - 4]
    caption = f"{body}\n\n{footer_text}"

    th_footer = f"\n\n출처: {source_names[0]}" + (" 외" if len(source_names) > 1 else "")
    if links:
        th_footer += f"\n{links[0]}"
    threads_text = card["threads_text"][: THREADS_MAX - len(th_footer)] + th_footer
    return caption, threads_text


def public_url(cfg: dict, rel_path: str) -> str:
    base = cfg.get("public_base_url") or ""
    if not base:
        repo, branch = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_REF_NAME", "main")
        if not repo:
            raise RuntimeError("공개 이미지 URL 을 만들 수 없습니다 (GitHub Actions 밖에서는 public_base_url 설정 필요)")
        base = f"https://raw.githubusercontent.com/{repo}/{branch}"
    return f"{base.rstrip('/')}/{rel_path}"


def expire_pending(cfg: dict, st: dict) -> None:
    limit = cfg.get("pending_expire_hours", 24) * 3600
    for card_id, entry in list(st["pending"].items()):
        if entry["status"] == "waiting" and time.time() - entry["created"] > limit:
            print(f"[main] {card_id} 승인 시간 초과로 폐기")
            if entry.get("tg_message_id") and telegram.enabled():
                telegram.clear_buttons(entry["tg_message_id"])
            del st["pending"][card_id]


# ── draft ────────────────────────────────────────────────

def cmd_draft(cfg: dict) -> None:
    st = state.load()
    expire_pending(cfg, st)

    items = sources.collect(cfg, state.posted_links(st))
    if not items:
        print("[draft] 수집된 헤드라인이 없습니다")
        return state.save(st)

    pick = writer.select_story(cfg, items, state.recent_titles(st))
    if pick["skip"] or not pick["related"]:
        print(f"[draft] 오늘은 건너뜀: {pick['why']}")
        return state.save(st)
    print(f"[draft] 선정: {pick['story']} ({pick['why']})")

    related = [items[i] for i in pick["related"] if 0 <= i < len(items)][:4]
    articles = []
    for it in related:
        if it["source"].startswith("Reddit"):
            # Reddit 항목은 링크된 원문 매체에서 본문을 가져온다
            it = {**it, "source": it["link"].split("/")[2].removeprefix("www.")}
        articles.append({**it, "text": article.fetch_text(it["link"])})

    card = writer.write_card(cfg, pick["story"], articles)
    print(f"[draft] 제목: {card['headline']}")

    card_id = datetime.now(KST).strftime("%Y%m%d-%H%M")
    OUTPUT_DIR.mkdir(exist_ok=True)
    image = images.get_image(cfg, card, OUTPUT_DIR / f"{card_id}-src.jpg")

    source_names = list(dict.fromkeys(a["source"] for a in articles))
    out = render.render(render.build_html(cfg, card, image, source_names), OUTPUT_DIR / f"{card_id}.jpg")
    links = [a["link"] for a in articles]
    caption, threads_text = build_captions(card, source_names, links, image)

    needs_approval = cfg.get("approval", True) or card["sensitive"]
    entry = {
        "id": card_id,
        "story": pick["story"],
        "links": links,
        "sources": source_names,
        "card": card,
        "caption": caption,
        "threads_text": threads_text,
        "image_path": out.relative_to(ROOT).as_posix(),
        "created": int(time.time()),
        "status": "waiting" if needs_approval else "approved",
        "attempts": 0,
    }
    if telegram.enabled():
        entry["tg_message_id"] = telegram.send_preview({**entry, "image_path": str(out)}, needs_approval)
    elif needs_approval:
        print("[draft] 텔레그램이 설정되지 않아 승인 요청을 보낼 수 없습니다")
    st["pending"][card_id] = entry
    state.save(st)

    print(f"\n[draft] 카드: {out}\n\n{caption}\n\n--- 스레드 ---\n{threads_text}")


# ── poll ─────────────────────────────────────────────────

def handle_telegram(st: dict) -> None:
    chat_id = str(env("TELEGRAM_CHAT_ID"))
    for upd in telegram.get_updates(st.get("tg_offset", 0)):
        st["tg_offset"] = upd["update_id"] + 1
        cq = upd.get("callback_query")
        if not cq or str(cq["message"]["chat"]["id"]) != chat_id:
            continue
        action, _, card_id = cq.get("data", "").partition(":")
        entry = st["pending"].get(card_id)
        if not entry or entry["status"] != "waiting":
            telegram.answer(cq["id"], "이미 처리됐거나 만료된 카드입니다")
            continue
        if action == "approve":
            entry["status"] = "approved"
            telegram.answer(cq["id"], "승인! 곧 게시합니다")
        elif action == "reject":
            del st["pending"][card_id]
            telegram.answer(cq["id"], "버렸습니다")
        telegram.clear_buttons(cq["message"]["message_id"])


def publish_approved(cfg: dict, st: dict) -> None:
    for card_id, entry in list(st["pending"].items()):
        if entry["status"] != "approved":
            continue
        url = public_url(cfg, entry["image_path"])
        done = entry.setdefault("published", {})
        try:
            if "instagram" in cfg["platforms"] and "instagram" not in done:
                done["instagram"] = publish.instagram(cfg, url, entry["caption"])
            if "threads" in cfg["platforms"] and "threads" not in done:
                done["threads"] = publish.threads(url, entry["threads_text"])
        except Exception as e:  # noqa: BLE001 - 어떤 실패든 텔레그램으로 알리고 다음 실행에서 재시도
            entry["attempts"] += 1
            msg = f"❌ {card_id} 게시 실패 ({entry['attempts']}/3): {e}"
            print(msg)
            if entry["attempts"] >= 3:
                entry["status"] = "failed"
                msg += "\n3번 실패해서 중단합니다."
            if telegram.enabled():
                telegram.send_text(msg[:4000])
            continue
        state.mark_posted(st, card_id, {})
        links = "\n".join(f"{k}: {v}" for k, v in done.items())
        print(f"[poll] 게시 완료 {card_id}\n{links}")
        if telegram.enabled():
            telegram.send_text(f"✅ 게시 완료 · {entry['story']}\n{links}")


def cmd_poll(cfg: dict) -> None:
    st = state.load()
    if telegram.enabled():
        handle_telegram(st)
    publish_approved(cfg, st)
    expire_pending(cfg, st)
    state.save(st)


# ── 보조 명령 ─────────────────────────────────────────────

def cmd_sample(cfg: dict) -> None:
    """API 키 없이 카드 디자인만 확인한다 (Commons 사진 검색은 실제로 함)."""
    card = {
        "headline": "아이슬란드 화산 또 폭발\n1년새 열 번째",
        "subheadline": "인근 마을 주민 대피… 블루라군도 임시 휴업",
        "tag": "유럽",
    }
    OUTPUT_DIR.mkdir(exist_ok=True)
    cands = images.search_commons("Sundhnúkur eruption Iceland", cfg["image"].get("min_width", 900))
    image = {"path": None, "credit": ""}
    if cands:
        c = cands[0]
        data = images._download(c["thumb_url"])
        if data:
            path = OUTPUT_DIR / "sample-src.jpg"
            path.write_bytes(data)
            image = {"path": path, "credit": f"자료사진 · {c['author']} / Wikimedia Commons ({c['license']})"}
    out = render.render(render.build_html(cfg, card, image, ["BBC", "Guardian", "Reuters"]),
                        OUTPUT_DIR / "sample.jpg")
    out2 = render.render(render.build_html(cfg, card, {"path": None, "credit": ""}, ["BBC"]),
                         OUTPUT_DIR / "sample-nophoto.jpg")
    print(f"샘플 카드: {out}\n사진 없는 버전: {out2}")


def cmd_chat_id() -> None:
    updates = telegram._call("getUpdates")
    if not updates:
        print("먼저 텔레그램에서 내 봇에게 아무 메시지나 보낸 뒤 다시 실행하세요.")
    for u in updates:
        chat = (u.get("message") or {}).get("chat")
        if chat:
            print(f"chat id: {chat['id']}  ({chat.get('first_name') or chat.get('title')})")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    commands = {
        "draft": lambda: cmd_draft(cfg),
        "poll": lambda: cmd_poll(cfg),
        "sample": lambda: cmd_sample(cfg),
        "chat-id": cmd_chat_id,
        "refresh-tokens": lambda: publish.refresh_tokens(cfg),
    }
    if cmd not in commands:
        print(__doc__)
        sys.exit(1)
    commands[cmd]()


if __name__ == "__main__":
    main()
