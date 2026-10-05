#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python_bin="${PYTHON311:-python3.11}"

if ! command -v "$python_bin" >/dev/null 2>&1; then
  echo "Нужен Python 3.11. Установите его или задайте PYTHON311=/path/to/python3.11" >&2
  exit 2
fi

for stand in person_face hands_gestures virtual_table; do
  env_dir="$root_dir/$stand/.venv"
  if [[ ! -x "$env_dir/bin/python" ]]; then
    "$python_bin" -m venv "$env_dir"
  fi
  "$env_dir/bin/python" -m pip install --upgrade pip
  if [[ "$stand" == "person_face" ]]; then
    "$env_dir/bin/python" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
  fi
  "$env_dir/bin/python" -m pip install -r "$root_dir/$stand/requirements.txt"
  if [[ "$stand" == "hands_gestures" ]]; then
    # MediaPipe Vision tolerates this optional audio dependency being absent;
    # PortAudio initialization hangs on this camera-only workstation.
    "$env_dir/bin/python" -m pip uninstall -y sounddevice
  fi
  if [[ "$stand" == "person_face" ]]; then
    "$env_dir/bin/python" -m pip install --no-deps ultralytics==8.4.173
  fi
  "$env_dir/bin/python" -m pip freeze > "$root_dir/$stand/requirements.lock.txt"
done

if [[ "${1:-}" == "--models" ]]; then
  "$root_dir/person_face/.venv/bin/python" "$root_dir/download_models.py"
fi

echo "Окружения готовы. Запуск: python3.11 $root_dir/launcher.py"
