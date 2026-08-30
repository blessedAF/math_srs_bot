"""
Рендер карточек в PNG: кириллица через системный шрифт, формулы — matplotlib mathtext.
В тексте карточки LaTeX выделяется $...$ или $$...$$.
"""

from __future__ import annotations

import io
import logging
import re
import textwrap
from functools import lru_cache
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import numpy as np
from matplotlib import colors as mcolors
from matplotlib import mathtext
from matplotlib.font_manager import FontProperties
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

CARD_W = 1080
BG = (244, 239, 228, 255)
INK = (32, 26, 18, 255)
MUTED = (110, 96, 74, 255)
ACCENT = (139, 90, 43, 255)
RULE = (196, 184, 150, 255)
PAD = 48

_MATH_SPLIT = re.compile(r"(\$\$.*?\$\$|\$(?:\\\$|[^$])+\$)", re.DOTALL)

_FONT_REGULAR = [
    Path(r"C:\Windows\Fonts\segoeui.ttf"),
    Path(r"C:\Windows\Fonts\arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    Path("/usr/share/fonts/truetype/freefont/FreeSans.ttf"),
]
_FONT_BOLD = [
    Path(r"C:\Windows\Fonts\segoeuib.ttf"),
    Path(r"C:\Windows\Fonts\arialbd.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"),
]


def _first_font(candidates: list[Path], size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return _first_font(_FONT_BOLD if bold else _FONT_REGULAR, size)


def _is_math(chunk: str) -> bool:
    return chunk.startswith("$") and chunk.endswith("$") and len(chunk) >= 2


def _unwrap_math(chunk: str) -> str:
    body = chunk.strip()
    if body.startswith("$$") and body.endswith("$$"):
        body = body[2:-2]
    elif body.startswith("$") and body.endswith("$"):
        body = body[1:-1]
    return body.strip()


def sanitize_math(latex: str) -> str:
    """matplotlib mathtext не знает короткие \\ge/\\le и \\pmod."""
    s = re.sub(r"\\ge(?![a-zA-Z])", r"\\geq", latex)
    s = re.sub(r"\\le(?![a-zA-Z])", r"\\leq", s)
    s = s.replace(r"\iff", r"\Leftrightarrow")
    s = s.replace(r"\dfrac12", r"\frac{1}{2}")
    s = s.replace(r"\lvert", r"|").replace(r"\rvert", r"|")
    s = re.sub(r"\\pmod\{([^}]+)\}", r"\\,(\\mathrm{mod}\\, \1)", s)
    s = re.sub(r"\\pmod\s+([A-Za-z0-9_\\]+)", r"\\,(\\mathrm{mod}\\, \1)", s)
    s = s.replace(r"\|", r"\Vert ")
    return s


# Парсер переиспользуется между вызовами. 'agg' отдаёт готовый растр
# (маску покрытия) напрямую, без создания Figure/Axes и без прохода
# через PNG-кодирование/декодирование — это и есть основной источник
# ускорения по сравнению со старым Figure+savefig(bbox_inches="tight").
_MATH_PARSER = mathtext.MathTextParser("agg")


@lru_cache(maxsize=512)
def _render_latex_cached(expr: str, fontsize: int, color: str, dpi: int = 200) -> Image.Image:
    """Рендерит LaTeX-формулу в прозрачное RGBA-изображение напрямую из
    растровой маски matplotlib, без промежуточного PNG. Кэшируется по
    (expr, fontsize, color) — одна и та же формула, которую в spaced
    repetition показывают многократно (при показе ответа, при оценке,
    при повторных показах карточки через дни), рендерится только один
    раз за время жизни процесса.
    """
    prop = FontProperties(size=fontsize)
    raster = _MATH_PARSER.parse(expr, dpi=dpi, prop=prop)
    alpha = np.asarray(raster.image)  # маска покрытия (0..255), форма (h, w)

    r, g, b = (int(c * 255) for c in mcolors.to_rgb(color))
    h, w = alpha.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., 0] = r
    rgba[..., 1] = g
    rgba[..., 2] = b
    rgba[..., 3] = alpha
    return Image.fromarray(rgba, mode="RGBA")


def render_latex(latex: str, fontsize: int = 26, color: str = "#201a12") -> Image.Image:
    """Рендерит один LaTeX-фрагмент в прозрачный PNG."""
    expr = sanitize_math(latex.strip())
    if expr.startswith("$") and expr.endswith("$"):
        expr = expr[1:-1].strip()
    expr = rf"${expr}$"

    img = _render_latex_cached(expr, fontsize, color)

    max_w = CARD_W - 2 * PAD
    if img.width > max_w:
        ratio = max_w / img.width
        img = img.resize((max_w, max(1, int(img.height * ratio))), Image.Resampling.LANCZOS)
    return img


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    cur = words[0]
    for word in words[1:]:
        trial = f"{cur} {word}"
        if draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    return lines


def _paste(canvas: Image.Image, piece: Image.Image, y: int) -> int:
    x = (CARD_W - piece.width) // 2
    canvas.alpha_composite(piece, (x, y))
    return y + piece.height


def render_card(
    front: str,
    back: str,
    topic: str = "",
    *,
    revealed: bool = False,
    footer: str = "",
    progress: str = "",
) -> bytes:
    """Собирает карточку. Если revealed=False, формула скрыта."""
    title_font = _font(36, bold=True)
    topic_font = _font(22, bold=True)
    body_font = _font(26)
    small_font = _font(20)
    footer_font = _font(22)

    # Сначала меряем высоту на временном холсте
    scratch = Image.new("RGBA", (CARD_W, 4000), (0, 0, 0, 0))
    draw = ImageDraw.Draw(scratch)

    y = PAD
    if progress:
        draw.text((PAD, y), progress, font=small_font, fill=MUTED)
        y += 36

    title_lines = _wrap(draw, front, title_font, CARD_W - 2 * PAD)
    for line in title_lines:
        draw.text((PAD, y), line, font=title_font, fill=INK)
        y += 46
    y += 8

    if topic:
        badge = f"  {topic}  "
        tw = int(draw.textlength(badge, font=topic_font))
        bh = 40
        draw.rounded_rectangle((PAD, y, PAD + tw, y + bh), radius=12, fill=(232, 214, 176, 255))
        draw.text((PAD, y + 6), badge, font=topic_font, fill=ACCENT)
        y += bh + 22

    draw.line((PAD, y, CARD_W - PAD, y), fill=RULE, width=2)
    y += 28

    body_blocks: list[tuple[str, object]] = []

    if revealed:
        chunks = [c for c in _MATH_SPLIT.split(back) if c != ""]
        if len(chunks) == 1 and not _is_math(chunks[0]) and back.strip():
            # Если пользователь вставил «голый» LaTeX без $...$, пробуем как формулу
            try:
                img = render_latex(back.strip())
                body_blocks.append(("math", img))
            except Exception:
                log.exception("latex fallback failed, drawing as text")
                body_blocks.append(("text", back.strip()))
        else:
            for chunk in chunks:
                if _is_math(chunk):
                    try:
                        img = render_latex(_unwrap_math(chunk))
                        body_blocks.append(("math", img))
                    except Exception:
                        log.exception("не удалось срендерить LaTeX: %s", chunk)
                        body_blocks.append(("text", chunk))
                elif chunk.strip():
                    body_blocks.append(("text", chunk.strip()))
    else:
        body_blocks.append(("hidden", "формула скрыта — нажми «Показать ответ»"))

    for kind, payload in body_blocks:
        if kind == "math":
            img = payload
            y += 8
            y += img.height + 16
        elif kind == "hidden":
            y += 80
        else:
            for line in textwrap.wrap(str(payload), width=52) or [""]:
                y += 36
            y += 8

    if footer:
        y += 20
        y += 40

    height = max(y + PAD, 420)
    canvas = Image.new("RGBA", (CARD_W, height), BG)
    draw = ImageDraw.Draw(canvas)

    y = PAD
    if progress:
        draw.text((PAD, y), progress, font=small_font, fill=MUTED)
        y += 36
    for line in title_lines:
        draw.text((PAD, y), line, font=title_font, fill=INK)
        y += 46
    y += 8
    if topic:
        badge = f"  {topic}  "
        tw = int(draw.textlength(badge, font=topic_font))
        bh = 40
        draw.rounded_rectangle((PAD, y, PAD + tw, y + bh), radius=12, fill=(232, 214, 176, 255))
        draw.text((PAD, y + 6), badge, font=topic_font, fill=ACCENT)
        y += bh + 22
    draw.line((PAD, y, CARD_W - PAD, y), fill=RULE, width=2)
    y += 28

    for kind, payload in body_blocks:
        if kind == "math":
            y = _paste(canvas, payload, y + 8) + 16
        elif kind == "hidden":
            draw.text((PAD, y + 24), str(payload), font=body_font, fill=MUTED)
            y += 80
        else:
            for line in _wrap(draw, str(payload), body_font, CARD_W - 2 * PAD):
                draw.text((PAD, y), line, font=body_font, fill=INK)
                y += 36
            y += 8

    if footer:
        draw.line((PAD, y + 8, CARD_W - PAD, y + 8), fill=RULE, width=2)
        y += 24
        draw.text((PAD, y), footer, font=footer_font, fill=ACCENT)

    out = io.BytesIO()
    # optimize=True пересчитывает PNG-фильтры несколько раз ради чуть
    # меньшего файла — это стоило ~80% времени всего рендера карточки
    # (см. профилирование). Telegram всё равно перекодирует фото на своей
    # стороне, так что compress_level=1 (быстрое сжатие) даёт файл чуть
    # крупнее, но рендерится в разы быстрее.
    canvas.convert("RGB").save(out, format="PNG", compress_level=1)
    return out.getvalue()


def as_input_file(png: bytes, name: str = "card.png"):
    from aiogram.types import BufferedInputFile

    return BufferedInputFile(png, filename=name)
