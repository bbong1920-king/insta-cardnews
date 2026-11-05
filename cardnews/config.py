import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
TEMPLATE_DIR = ROOT / "templates"

USER_AGENT = "cardnews-bot/1.0 (+https://github.com/{})".format(
    os.environ.get("GITHUB_REPOSITORY", "local")
)


def _load_dotenv():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config() -> dict:
    _load_dotenv()
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def env(name: str, required: bool = False) -> str:
    value = os.environ.get(name, "")
    if required and not value:
        raise RuntimeError(f"환경변수 {name} 가 설정되지 않았습니다 (.env 또는 GitHub Secrets 확인)")
    return value
