import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STANDS = {
    "person-face": ROOT / "person_face",
    "hands-gestures": ROOT / "hands_gestures",
    "virtual-table": ROOT / "virtual_table",
}

def command_for(name, source, participants_file):
    directory = STANDS[name]
    python = directory / ".venv/bin/python"
    if not python.exists():
        raise SystemExit(f"Нет окружения {directory / '.venv'}. Запустите ./setup_experiments.sh --models")
    command = [str(python), str(directory / "app.py")]
    if name != "virtual-table": command += ["--source", source]
    elif participants_file: command += ["--participants-file", participants_file]
    return command

def main():
    parser = argparse.ArgumentParser(description="Launcher экспериментальных стендов Automatic Mafia")
    parser.add_argument("stand", choices=[*STANDS, "all"], nargs="?", default="all")
    parser.add_argument("--source", default="0", help="камера, видео или RTSP URL")
    parser.add_argument("--participants-file", default=str(ROOT / "person_face/results/participants.json"))
    args = parser.parse_args()
    names = list(STANDS) if args.stand == "all" else [args.stand]
    processes = [subprocess.Popen(command_for(name, args.source, args.participants_file), cwd=STANDS[name]) for name in names]
    try:
        return max(process.wait() for process in processes)
    except KeyboardInterrupt:
        for process in processes:
            process.terminate()
        return 130

if __name__ == "__main__": raise SystemExit(main())
