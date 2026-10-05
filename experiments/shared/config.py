import json
from pathlib import Path

def load_json(path: str | Path, default: dict) -> dict:
    p = Path(path)
    if not p.exists():
        return default.copy()
    try:
        value = json.loads(p.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else default.copy()
    except (OSError, ValueError):
        return default.copy()

def save_json(path: str | Path, value: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
