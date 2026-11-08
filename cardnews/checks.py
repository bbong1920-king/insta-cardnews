"""생성된 카드 문구를 코드로 점검한다. Claude 를 부르지 않으므로 구독 사용량이 들지 않는다."""
import re

# 프롬프트의 목표치(900~1400자)보다 조금 넉넉하게 잡아 사소한 차이로 다시 쓰지 않게 한다
CAPTION_RANGE = (800, 1500)
HEADLINE_MAX = 30
SUBHEADLINE_MAX = 45
TAG_MAX = 6
# 프롬프트의 목표치(200자)보다 조금 넉넉하게 잡는다
THREADS_MAX = 230
THREADS_LINES = (3, 5)
BAIT_WORDS = ("충격", "경악", "발칵", "이것", "그 이유", "알고 보니")

# 뉴스 유형별 설명글 소제목. '기타'는 소제목을 자유롭게 정한다
STORY_SECTIONS = {
    "사건": ["무슨 일이?", "어떻게 벌어졌나", "왜 중요한가", "앞으로"],
    "인물": ["무슨 일이?", "어떤 사람인가", "왜 화제인가", "앞으로"],
    "정책": ["무엇이 바뀌나", "왜 나왔나", "누가 영향을 받나", "언제부터"],
    "연구": ["무엇을 알아냈나", "어떻게 알아냈나", "어디에 쓰이나", "한계는"],
}

_NUMBER = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_KO_UNIT = "천만|백만|천|만|억|조"
_KO_UNITS = {"천": 1e3, "만": 1e4, "백만": 1e6, "천만": 1e7, "억": 1e8, "조": 1e12}
_EN_UNITS = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9, "trillion": 1e12}
_EN_NUMBER = re.compile(rf"({_NUMBER})(?:\s*(thousand|million|billion|trillion|bn|m|k)\b)?", re.I)
# "8만5000명", "1억 5000만"처럼 단위가 이어지면 한 숫자로 읽는다
_KO_NUMBER = re.compile(rf"(?:(?:{_NUMBER})\s*(?:{_KO_UNIT})\s*)+(?:\d+)?[가-힣%]{{0,2}}|(?:{_NUMBER})[가-힣%]{{0,2}}")
_KO_PART = re.compile(rf"({_NUMBER})\s*({_KO_UNIT})?")


def plain_headline(headline: str) -> str:
    return headline.replace("\\n", " ").replace("\n", " ").strip()


def _to_float(number: str) -> float:
    return float(number.replace(",", ""))


def check_card(card: dict) -> list[str]:
    """글자 수, 소제목, 낚시 표현을 점검한다. 문제가 있으면 다시 쓰게 할 지시문 목록을 돌려준다."""
    problems = []
    headline = plain_headline(card["headline"])
    limits = [
        ("headline", headline, HEADLINE_MAX),
        ("subheadline", card["subheadline"], SUBHEADLINE_MAX),
        ("tag", card["tag"], TAG_MAX),
        ("threads_text", card["threads_text"], THREADS_MAX),
    ]
    for name, text, limit in limits:
        if len(text) > limit:
            problems.append(f"{name} 가 {len(text)}자입니다. {limit}자 이내로 줄이세요.")

    lines = [line for line in card["threads_text"].splitlines() if line.strip()]
    if not THREADS_LINES[0] <= len(lines) <= THREADS_LINES[1]:
        problems.append(f"threads_text 가 {len(lines)}줄입니다. 한 줄에 한 문장씩 3~5줄로 나누세요.")

    low, high = CAPTION_RANGE
    if not low <= len(card["caption_body"]) <= high:
        problems.append(f"caption_body 가 {len(card['caption_body'])}자입니다. 900~1400자로 맞추세요.")

    headings = [h.strip() for h in re.findall(r"📌\s*(.+)", card["caption_body"])]
    allowed = STORY_SECTIONS.get(card["story_type"])
    if len(headings) < 2:
        problems.append("caption_body 에 📌 소제목을 2개 이상 쓰세요.")
    if allowed and any(h not in allowed for h in headings):
        problems.append(f"story_type 이 {card['story_type']}이면 소제목은 {', '.join(allowed)} 중에서만 쓰세요.")

    title = f"{headline} {card['subheadline']}"
    for word in BAIT_WORDS:
        if word in title:
            problems.append(f"제목에 '{word}' 같은 표현을 쓰지 말고 핵심 사실을 직접 쓰세요.")
    return problems


def _source_values(text: str) -> set[float]:
    values = set()
    for match in _EN_NUMBER.finditer(text):
        value = _to_float(match.group(1))
        # "10m"은 10미터일 수도 있으므로 단위를 뺀 값도 함께 인정한다
        values.add(round(value, 3))
        values.add(round(value * _EN_UNITS.get((match.group(2) or "").lower(), 1), 3))
    return values


def _korean_value(token: str) -> float:
    total = sum(_to_float(num) * _KO_UNITS.get(unit, 1) for num, unit in _KO_PART.findall(token))
    return round(total, 3)


def unverified_numbers(card: dict, articles: list[dict]) -> list[str]:
    """카드 문구의 숫자 중 원문에서 찾지 못한 것을 돌려준다.

    계산한 값("23년 만에")이나 다르게 적힌 값도 잡히므로 게시를 막지 않고 승인자에게 경고만 한다.
    한 자리 정수는 원문에 "two"처럼 단어로 적히는 경우가 많아 제외한다.
    """
    known = _source_values(" ".join(f"{a['title']} {a['summary']} {a['text']}" for a in articles))
    written = " ".join([card["headline"], card["subheadline"], card["caption_body"], card["threads_text"]])
    missing = {}  # 같은 값이 "10월", "10월에"처럼 여러 번 나와도 한 번만 알린다
    for match in _KO_NUMBER.finditer(written):
        value = _korean_value(match.group(0))
        if value not in known and not (value < 10 and value == int(value)):
            missing.setdefault(value, match.group(0))
    return list(missing.values())
