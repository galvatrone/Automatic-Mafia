import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "automatic-mafia.experiments.participants/v1"

def write_participants(path, participants, source):
    payload = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "participants": participants,
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)

def read_participants(path):
    source = Path(path).resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA:
        raise ValueError(f"неподдерживаемая схема: {payload.get('schema')!r}")
    participants = payload.get("participants")
    if not isinstance(participants, list):
        raise ValueError("participants должен быть списком")
    clean = []
    seen = set()
    for raw in participants:
        person_id = str(raw.get("person_id", "")).strip()
        if not person_id or person_id in seen:
            continue
        seen.add(person_id)
        clean.append({
            "person_id": person_id,
            "label": str(raw.get("label") or person_id),
            "photo_path": str(raw.get("photo_path") or ""),
            "last_seen_ns": int(raw.get("last_seen_ns") or 0),
        })
    if not clean:
        raise ValueError("файл не содержит уникальных участников")
    return clean
