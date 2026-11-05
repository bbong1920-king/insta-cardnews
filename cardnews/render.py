"""HTML 템플릿을 1080x1350 JPEG 카드로 렌더링 (인스타그램 API 는 JPEG 만 받는다)."""
import base64
import html
import mimetypes
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

from .config import TEMPLATE_DIR


def _fill(template: str, values: dict) -> str:
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def build_html(cfg: dict, card: dict, image: dict, sources: list[str]) -> str:
    brand = cfg["brand"]
    if image.get("path"):
        path = Path(image["path"])
        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        data = base64.b64encode(path.read_bytes()).decode()
        photo_bg = f'url("data:{mime};base64,{data}")'
        body_class = ""
        # 세로 사진은 인물 얼굴이 위쪽에 있으므로 위에 맞춰 자른다
        with Image.open(path) as img:
            portrait = img.height > img.width
        photo_pos = "center 4%" if portrait else "center 30%"
    else:
        photo_bg = "radial-gradient(120% 90% at 80% 10%, #2b3a67 0%, #141826 55%, #0c0d10 100%)"
        body_class = "no-photo"
        photo_pos = "center"

    template = (TEMPLATE_DIR / "card.html").read_text(encoding="utf-8")
    return _fill(template, {
        "accent": brand.get("accent", "#FF4D4F"),
        "photo_bg": photo_bg,
        "photo_pos": photo_pos,
        "body_class": body_class,
        "brand": html.escape(brand["name"]),
        "tag": html.escape(card["tag"]),
        "credit": html.escape(image.get("credit", "")),
        "headline": html.escape(card["headline"].replace("\\n", "\n")),
        "subheadline": html.escape(card["subheadline"]),
        "sources": html.escape(" · ".join(sources[:3])),
    })


def render(page_html: str, out_path: Path) -> Path:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=1)
        page.set_content(page_html, wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        page.evaluate("window.fitHeadline()")
        page.screenshot(path=str(out_path), type="jpeg", quality=92,
                        clip={"x": 0, "y": 0, "width": 1080, "height": 1350})
        browser.close()
    return out_path
