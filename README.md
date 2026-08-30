# Math SRS Bot

Telegram-бот для spaced repetition (SM-2) по формулам и теоремам олимпиадной математики.

Карточки рисуются картинкой: кириллица обычным шрифтом, формулы — LaTeX (`$...$`). Telegram сам TeX не рендерит, поэтому бот собирает PNG.

## Запуск (Windows, тест)

1. Токен у [@BotFather](https://t.me/BotFather) (`/newbot`).
2. `python -m venv venv` и `venv\Scripts\activate`
3. `pip install -r requirements.txt`
4. Скопировать `.env.example` в `.env` и вписать `BOT_TOKEN=...`
5. `python bot.py`

## Команды

Меню внизу экрана после `/start`:

- **Добавить карточку** — вопрос → ответ → тема. В ответе можно писать LaTeX: `$c^2=a^2+b^2-2ab\cos C$`
- **Повторить** — due-карточки картинкой, оценка 😵 / 🙂 / 😎
- **Список / Статистика / Помощь**

Слэш-команды те же: `/add`, `/review`, `/list`, `/stats`, `/delete <id>`, `/cancel`.

`/start` показывает твой Telegram ID — он нужен для заливки seed.

## Пополнение базы

В `seed_cards.json` — 136 карточек олимпиадного уровня (неравенства, теория чисел, комбинаторика, геометрия, алгебра), без школьной базы вроде Пифагора.

```
python import_seed.py <telegram_user_id>
```

Повторный запуск **не дублирует** карточки с тем же названием: обновляет формулировку, прогресс SM-2 не сбрасывает. Новые карточки из файла дописываются.

## Структура

- `bot.py` — aiogram, FSM
- `render.py` — PNG-карточки (Pillow + matplotlib mathtext)
- `db.py` — SQLite
- `sm2.py` — SM-2, три градации
- `seed_cards.json` / `import_seed.py`
- `cards.db` — создаётся при первом запуске, в git не входит

## Деплой на старый ноут с Ubuntu

Нужны: интернет, пользователь с sudo, токен бота. Бот работает **long polling** (отдельный домен и webhook не обязательны).

### 1. Один раз на ноуте

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-pip fonts-dejavu-core
# чтобы крышка/простой не уводили машину в сон:
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
```

На ноутбуке ещё имеет смысл в настройках питания поставить «не засыпать при питании от сети» и не закрывать крышку (или `HandleLidSwitch=ignore` в `/etc/systemd/logind.conf`).

### 2. Клон и зависимости

```bash
cd ~
git clone https://github.com/blessedAF/math_srs_bot.git
cd math_srs_bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env   # BOT_TOKEN=...
```

### 3. Карточки

Запусти бота один раз (`python bot.py`), в Telegram напиши `/start`, скопируй ID, останови (`Ctrl+C`):

```bash
python import_seed.py 123456789
```

### 4. systemd — автозапуск после ребута

В `deploy/math-srs.service` замени `REPLACE_USER` на имя пользователя Linux (и путь, если репозиторий лежит не в `/home/USER/math_srs_bot`).

```bash
sudo cp deploy/math-srs.service /etc/systemd/system/math-srs.service
sudo nano /etc/systemd/system/math-srs.service
sudo systemctl daemon-reload
sudo systemctl enable --now math-srs
sudo systemctl status math-srs
```

Логи: `journalctl -u math-srs -f`

Обновление с GitHub:

```bash
cd ~/math_srs_bot
git pull
source venv/bin/activate
pip install -r requirements.txt
python import_seed.py ТВОЙ_ID    # подтянуть новые формулировки
sudo systemctl restart math-srs
```

Можно вместо ручных шагов 2–4 выполнить `bash deploy/install-ubuntu.sh` из корня репозитория (после того как `.env` уже создан).
