"""
Заливает карточки из seed_cards.json в базу для указанного user_id.

Использование:
    python import_seed.py <твой_telegram_user_id>

Узнать свой user_id можно у бота @userinfobot в Telegram.
"""

import json
import sys
from pathlib import Path

import db

SEED_PATH = Path(__file__).parent / "seed_cards.json"


def main() -> None:
    if len(sys.argv) != 2:
        print("Использование: python import_seed.py <твой_telegram_user_id>")
        sys.exit(1)

    user_id = int(sys.argv[1])
    cards = json.loads(SEED_PATH.read_text(encoding="utf-8"))

    db.init_db()
    added = 0
    for card in cards:
        db.add_card(
            user_id=user_id,
            front=card["front"],
            back=card["back"],
            topic=card.get("topic", ""),
        )
        added += 1

    print(f"Добавлено {added} карточек для user_id={user_id}")


if __name__ == "__main__":
    main()
