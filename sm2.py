"""
SM-2 spaced repetition algorithm (упрощённый, 3 градации оценки).

Оценки, которые вводит пользователь:
    "again" (плохо) -> quality = 2  -> сброс интервала
    "good"  (норм)  -> quality = 4  -> нормальный рост интервала
    "easy"  (легко) -> quality = 5  -> усиленный рост интервала
"""

from dataclasses import dataclass
from datetime import date, timedelta

GRADE_TO_QUALITY = {
    "again": 2,
    "good": 4,
    "easy": 5,
}


@dataclass
class ReviewState:
    ease: float
    interval: int
    repetitions: int


def review(state: ReviewState, grade: str) -> ReviewState:
    """Считает новое состояние карточки после оценки пользователем."""
    quality = GRADE_TO_QUALITY[grade]

    ease = state.ease
    interval = state.interval
    repetitions = state.repetitions

    if quality < 3:
        # Плохо вспомнил — начинаем цикл заново, но ease не обнуляем полностью
        repetitions = 0
        interval = 1
    else:
        if repetitions == 0:
            interval = 1
        elif repetitions == 1:
            interval = 6
        else:
            interval = round(interval * ease)
        repetitions += 1

    ease = ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ease = max(ease, 1.3)

    return ReviewState(ease=ease, interval=interval, repetitions=repetitions)


def next_review_date(interval_days: int, today: date | None = None) -> date:
    today = today or date.today()
    return today + timedelta(days=interval_days)
