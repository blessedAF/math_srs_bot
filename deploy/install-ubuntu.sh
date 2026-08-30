#!/usr/bin/env bash
# Установка бота на Ubuntu (запускать из клона репозитория).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Создай $ROOT/.env с BOT_TOKEN=... (см. .env.example)" >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip fonts-dejavu-core git

python3 -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate
pip install -U pip
pip install -r requirements.txt

echo
echo "venv готов. Дальше:"
echo "  1) python import_seed.py <твой_telegram_id>"
echo "  2) sudo cp deploy/math-srs.service /etc/systemd/system/math-srs.service"
echo "     и замени REPLACE_USER на своего пользователя и путь, если клон не в /home/USER/math_srs_bot"
echo "  3) sudo systemctl daemon-reload && sudo systemctl enable --now math-srs"
echo "  4) отключить сон ноутбука, если это сервер:"
echo "     sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target"
