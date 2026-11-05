"""Claude 로 (1) 오늘 가장 화제인 뉴스를 고르고 (2) 한국어 카드 문구와 설명글을 쓴다.

config.yaml 의 llm 값에 따라 두 가지 방식으로 Claude 를 부른다.
- claude-code: Claude Code CLI (`claude -p`) + 구독 토큰 → 추가 비용 없음, 구독 사용량을 씀
- api:         Claude API + ANTHROPIC_API_KEY → 사용량만큼 과금
"""
import base64
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import env

_client = None


def client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))
    return _client


def _claude_bin() -> str:
    path = shutil.which("claude")
    if not path:
        raise RuntimeError("claude CLI 가 없습니다: npm install -g @anthropic-ai/claude-code")
    # Windows 의 npm 은 .cmd 래퍼를 깔아서 줄바꿈이 든 인자가 깨진다 → 실제 실행 파일을 직접 부른다
    if path.lower().endswith(".cmd"):
        exe = Path(path).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        if exe.exists():
            return str(exe)
    return path


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": props,
        "required": required if required is not None else list(props),
        "additionalProperties": False,
    }


STR = {"type": "string"}
INT = {"type": "integer"}
BOOL = {"type": "boolean"}


def _ask(cfg: dict, system: str, text: str, schema: dict,
         images: list[bytes] | None = None, max_tokens: int = 16000) -> dict:
    if cfg.get("llm", "claude-code") == "api":
        return _ask_api(cfg, system, text, schema, images, max_tokens)
    return _ask_cli(cfg, system, text, schema, images)


def _ask_cli(cfg: dict, system: str, text: str, schema: dict, images: list[bytes] | None) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        tools = ""
        if images:
            # CLI 에는 이미지를 직접 못 넘기므로 파일로 저장하고 Read 도구로 보게 한다
            names = []
            for i, data in enumerate(images):
                (Path(tmp) / f"{i}.jpg").write_bytes(data)
                names.append(f"./{i}.jpg")
            text += "\n\n후보 이미지 파일 (Read 도구로 모두 열어서 보고 판단하세요): " + ", ".join(names)
            tools = "Read"

        cmd = [
            _claude_bin(), "-p",
            "--output-format", "json",
            "--json-schema", json.dumps(schema, ensure_ascii=False),
            "--system-prompt", system,
            "--tools", tools,
            "--no-session-persistence",
        ]
        if tools:
            cmd += ["--allowedTools", tools]
        if cfg.get("cli_model"):
            cmd += ["--model", cfg["cli_model"]]
        if cfg.get("effort"):
            cmd += ["--effort", cfg["effort"]]

        proc = subprocess.run(cmd, input=text, capture_output=True, text=True,
                              encoding="utf-8", cwd=tmp, timeout=900)

    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"claude CLI 실행 실패 (exit {proc.returncode}): {proc.stderr[-1000:] or proc.stdout[-1000:]}")
    if result.get("is_error") or "structured_output" not in result:
        raise RuntimeError(f"claude CLI 오류: {result.get('result')}")
    return result["structured_output"]


def _ask_api(cfg: dict, system: str, text: str, schema: dict,
             images: list[bytes] | None, max_tokens: int) -> dict:
    content = [{"type": "text", "text": text}]
    for data in images or []:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(data).decode()},
        })
    response = client().beta.messages.create(
        model=cfg.get("model", "claude-opus-5-5"),
        max_tokens=max_tokens,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={
            "effort": cfg.get("effort", "medium"),
            "format": {"type": "json_schema", "schema": schema},
        },
        system=system,
        messages=[{"role": "user", "content": content}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Claude 가 요청을 거절했습니다: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("응답이 max_tokens 에서 잘렸습니다")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


# ── 1단계: 뉴스 선정 ─────────────────────────────────────

SELECT_SYSTEM = """당신은 한국 인스타그램/스레드 '해외 화제 뉴스' 계정의 편집장입니다.
여러 외신의 최근 헤드라인 목록을 보고, 오늘 한 장의 카드뉴스로 만들 뉴스 1건을 고릅니다.

선정 기준 (중요한 순서):
1. 이미 '터진' 뉴스: 여러 매체가 동시에 다루고 있거나 Reddit 추천수가 높은 것
2. 한국 독자가 흥미를 느낄 만한 것 (놀랍다, 신기하다, 생활에 영향이 있다, 대화거리가 된다)
3. 한 장의 카드와 설명글로 이해할 수 있는 것
4. 최근 게시한 뉴스와 같은 사건이 아닌 것

피할 것: 한국 국내 뉴스(이미 한국어 보도가 충분함), 사실 확인이 안 된 루머,
추측성 단독 보도, 선정적이거나 잔혹한 묘사가 중심인 사건.
적당한 뉴스가 없으면 skip 을 true 로 하세요."""

SELECT_SCHEMA = _obj({
    "skip": BOOL,
    "story": {**STR, "description": "선정한 사건을 한 줄로 (한국어)"},
    "related": {"type": "array", "items": INT, "description": "이 사건을 다룬 헤드라인 번호들, 화제도 높은 순"},
    "why": {**STR, "description": "선정 이유 (한국어, 한두 문장)"},
})


def select_story(cfg: dict, items: list[dict], recent: list[str]) -> dict:
    lines = []
    for it in items:
        extra = f" [▲{it['score']} 💬{it['comments']}]" if "score" in it else ""
        lines.append(f"#{it['i']} ({it['source']}){extra} {it['title']} — {it['summary']}")
    content = (
        "최근 게시한 뉴스 (중복 금지):\n"
        + ("\n".join(f"- {t}" for t in recent) or "- (없음)")
        + "\n\n헤드라인 목록:\n"
        + "\n".join(lines)
    )
    return _ask(cfg, SELECT_SYSTEM, content, SELECT_SCHEMA, max_tokens=4000)


# ── 2단계: 카드 문구 + 설명글 작성 ─────────────────────────

WRITE_SYSTEM = """당신은 한국 인스타그램/스레드 '해외 화제 뉴스' 계정의 에디터입니다.
같은 사건을 다룬 외신 기사 여러 개를 읽고, 한국 독자용 카드뉴스 1장과 설명글을 씁니다.

반드시 지킬 것:
- 원문을 번역해서 옮기지 말고, 확인된 사실을 바탕으로 당신의 문장으로 새로 정리하세요.
  원문 문장을 그대로 인용하는 것은 짧은 발언 인용(따옴표) 정도만 허용됩니다.
- 기사들 사이에 내용이 다르거나 확인되지 않은 부분은 단정하지 말고 "~로 알려졌다", "~라고 밝혔다"처럼 쓰세요.
- 숫자, 이름, 날짜는 원문 그대로 정확히. 외국 인명/지명은 국립국어원 외래어 표기법을 따르세요.
- 자극적인 낚시 제목 금지. 흥미롭되 사실에 맞게.
- 존댓말이 아닌 뉴스체 (~했다, ~이다)로 쓰세요. 단, 설명글 마지막 한 줄은 독자에게 묻는 질문으로 끝내도 좋습니다.

필드 안내:
- headline: 카드 메인 제목. 띄어쓰기 포함 30자 이내. 줄바꿈이 필요하면 \\n 을 한 번만.
- subheadline: 제목 아래 한 줄 설명. 45자 이내.
- tag: 지역/분야 태그 2~6자 (예: "미국", "유럽", "우주", "기후")
- caption_body: 인스타그램 설명글 본문. 다음 구조로 900~1400자:
  첫 줄 훅(한 문장) / 빈 줄 / 📌 무슨 일이? / 📌 배경 / 📌 왜 중요한가 / 📌 반응·앞으로
  각 소제목 아래 2~4문장. 출처와 해시태그는 넣지 마세요 (코드가 자동으로 붙입니다).
- threads_text: 스레드용 글. 400자 이내, 핵심만 대화하듯.
- hashtags: 한국어 해시태그 5개 이하 (# 없이)
- image_queries: Wikimedia Commons 에서 찾을 영어 검색어 3개. 사건 현장 사진은 없으니
  관련 인물 이름, 장소/랜드마크, 사물처럼 자유 라이선스 사진이 있을 법한 것으로.
- ai_image_prompt: 적당한 사진이 없을 때 쓸 AI 이미지 프롬프트 (영어). 사건을 상징하는
  에디토리얼 일러스트 스타일. 실존 인물 얼굴, 글자, 로고, 실사 보도사진처럼 보이는 연출 금지.
- sensitive: 사망·재난·전쟁 피해·범죄 피해자 등 신중해야 하는 뉴스면 true
- fact_notes: 기사들끼리 엇갈리거나 불확실한 점 (없으면 빈 문자열). 승인자에게 보여줍니다."""

WRITE_SCHEMA = _obj({
    "headline": STR,
    "subheadline": STR,
    "tag": STR,
    "caption_body": STR,
    "threads_text": STR,
    "hashtags": {"type": "array", "items": STR},
    "image_queries": {"type": "array", "items": STR},
    "ai_image_prompt": STR,
    "sensitive": BOOL,
    "fact_notes": STR,
})


def write_card(cfg: dict, story: str, articles: list[dict]) -> dict:
    parts = [f"사건: {story}\n"]
    for a in articles:
        body = a["text"] or f"(본문 추출 실패, 요약만) {a['summary']}"
        parts.append(f"=== {a['source']}: {a['title']}\n{body}\n")
    return _ask(cfg, WRITE_SYSTEM, "\n".join(parts), WRITE_SCHEMA)


# ── 3단계: 후보 사진 중 고르기 (이미지 보고 판단) ─────────────

PICK_SYSTEM = """뉴스 카드뉴스의 대표 이미지로 쓸 '자료사진'을 고릅니다.
후보 사진들을 보고 뉴스와 가장 관련 있고 보기 좋은 1장을 고르세요.
기준: 뉴스 주제와 직접 관련 / 사진이 선명함 / 오해를 부르지 않음
(다른 사건 현장처럼 보이거나, 무관한 인물이 크게 나오는 사진은 안 됨).
지도·도표·문서 스캔·로고는 피하세요. 마땅한 게 없으면 -1."""

PICK_SCHEMA = _obj({"index": INT, "reason": STR})


def pick_image(cfg: dict, card: dict, candidates: list[dict]) -> int:
    text = (
        f"뉴스 제목: {card['headline']}\n부제: {card['subheadline']}\n\n"
        f"후보 {len(candidates)}장 (번호는 이미지 순서와 같음):\n"
        + "\n".join(f"[{i}] {c['title']}" for i, c in enumerate(candidates))
    )
    result = _ask(cfg, PICK_SYSTEM, text, PICK_SCHEMA,
                  images=[c["preview"] for c in candidates], max_tokens=2000)
    print(f"[writer] 사진 선택: {result['index']} ({result['reason']})")
    idx = result["index"]
    return idx if 0 <= idx < len(candidates) else -1
