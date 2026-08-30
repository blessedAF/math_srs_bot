"""
Заливает карточки из seed_cards.json в базу для указанного user_id.

Существующие карточки (тот же front у того же user_id) обновляются
(формула/тема), прогресс SM-2 не сбрасывается. Новые — добавляются.

Использование:
    python import_seed.py <твой_telegram_user_id>
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
    updated = 0
    for card in cards:
        front = card["front"]
        back = card["back"]
        topic = card.get("topic", "")
        existing = db.find_card_by_front(user_id, front)
        if existing is None:
            db.add_card(user_id=user_id, front=front, back=back, topic=topic)
            added += 1
        else:
            db.update_card_text(existing["id"], back, topic)
            updated += 1

    print(
        f"Готово для user_id={user_id}: добавлено {added}, "
        f"обновлено {updated}, всего в файле {len(cards)}"
    )


if __name__ == "__main__":
    main()
