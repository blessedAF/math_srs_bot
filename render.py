"""
Рендер карточек в PNG: кириллица через системный шрифт, формулы — matplotlib mathtext.
В тексте карточки LaTeX выделяется $...$ или $$...$$.
"""

from __future__ import annotations

import io
import logging
import re
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
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    Path("/usr/share/fonts/truetype/freefont/FreeSans.ttf"),
    Path(r"C:\Windows\Fonts\segoeui.ttf"),
    Path(r"C:\Windows\Fonts\arial.ttf"),
]
_FONT_BOLD = [
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"),
    Path(r"C:\Windows\Fonts\segoeuib.ttf"),
    Path(r"C:\Windows\Fonts\arialbd.ttf"),
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
# dpi=72 выбран специально: при нём 1pt fontsize == 1px, поэтому размер
# формулы в пикселях предсказуемо совпадает с fontsize — это позволяет
# подобрать INLINE_MATH_FONTSIZE так, чтобы маленькие формулы внутри
# предложения визуально сливались с обычным текстом по высоте и базовой
# линии, а не были каждая на отдельной строке огромным блоком.
_MATH_PARSER = mathtext.MathTextParser("agg")
_MATH_DPI = 72
DISPLAY_MATH_FONTSIZE = 72  # крупная формула на отдельной строке (было ~72px и при dpi=200,fontsize=26)
INLINE_MATH_FONTSIZE = 28  # подобрано опытным путём под BODY_FONT_SIZE=26


@lru_cache(maxsize=512)
def _render_latex_raw(expr: str, fontsize: int, color: str) -> tuple[Image.Image, float, float]:
    """Рендерит LaTeX-формулу в прозрачное RGBA-изображение напрямую из
    растровой маски matplotlib, без промежуточного PNG. Возвращает
    (картинка, height, depth) — height/depth нужны для выравнивания по
    базовой линии при вставке формулы в поток текста. Кэшируется по
    (expr, fontsize, color) — одна и та же формула, которую в spaced
    repetition показывают многократно, рендерится только один раз за
    время жизни процесса.
    """
    prop = FontProperties(size=fontsize)
    raster = _MATH_PARSER.parse(expr, dpi=_MATH_DPI, prop=prop)
    alpha = np.asarray(raster.image)  # маска покрытия (0..255), форма (h, w)

    r, g, b = (int(c * 255) for c in mcolors.to_rgb(color))
    h, w = alpha.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., 0] = r
    rgba[..., 1] = g
    rgba[..., 2] = b
    rgba[..., 3] = alpha
    img = Image.fromarray(rgba, mode="RGBA")
    return img, raster.height, raster.depth


def _prepare_expr(latex: str) -> str:
    expr = sanitize_math(latex.strip())
    if expr.startswith("$") and expr.endswith("$"):
        expr = expr[1:-1].strip()
    return rf"${expr}$"


def render_latex(latex: str, fontsize: int = DISPLAY_MATH_FONTSIZE, color: str = "#201a12") -> Image.Image:
    """Рендерит один LaTeX-фрагмент в прозрачный PNG (для крупных display-формул)."""
    expr = _prepare_expr(latex)
    img, _height, _depth = _render_latex_raw(expr, fontsize, color)

    max_w = CARD_W - 2 * PAD
    if img.width > max_w:
        ratio = max_w / img.width
        img = img.resize((max_w, max(1, int(img.height * ratio))), Image.Resampling.LANCZOS)
    return img


def render_inline_math(latex: str, color: str = "#201a12") -> tuple[Image.Image, int]:
    """Рендерит формулу в размере, подобранном под обычный текст (для
    вставки внутрь предложения). Возвращает (картинка, depth_px) —
    depth нужен вызывающему коду, чтобы выровнять формулу по базовой
    линии окружающего текста.
    """
    expr = _prepare_expr(latex)
    img, height, depth = _render_latex_raw(expr, INLINE_MATH_FONTSIZE, color)
    return img, round(depth)


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


def _split_paragraphs(text: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]


_GLUE_LEFT = re.compile(r"^[,.;:!?)\]}]")
_OPEN_BRACKETS = set("([{")


def _tokenize_paragraph(paragraph: str) -> list[tuple[str, str, bool]]:
    """Разбивает параграф на атомы потока: ('word'|'math', payload, glue_left).
    glue_left=True означает «не ставить пробел перед этим атомом» —
    нужно для запятых/точек (глядя назад) и для атомов сразу после
    открывающей скобки вроде "(" (глядя вперёд)."""
    atoms: list[tuple[str, str, bool]] = []
    pending_glue = False  # следующий атом клеится к предыдущему без пробела
    for chunk in _MATH_SPLIT.split(paragraph):
        if chunk == "":
            continue
        if _is_math(chunk):
            atoms.append(("math", _unwrap_math(chunk), pending_glue))
            pending_glue = False
        else:
            for word in chunk.split():
                glue = pending_glue or (bool(atoms) and bool(_GLUE_LEFT.match(word)))
                atoms.append(("word", word, glue))
                pending_glue = bool(word) and word[-1] in _OPEN_BRACKETS
    return atoms


def _layout_flow(
    draw: ImageDraw.ImageDraw, atoms: list[tuple[str, str, bool]], body_font, max_width: int
) -> tuple[list[dict], int]:
    """Раскладывает смешанный текст+формулы по строкам с переносом,
    выравнивая всё по общей базовой линии — так короткие формулы
    вроде "$f$" или "$w_i \\ge 0$" встраиваются в предложение как
    обычное слово, а не превращаются в отдельный гигантский блок.
    """
    asc, desc = body_font.getmetrics()
    space_w = draw.textlength(" ", font=body_font)

    lines: list[dict] = []
    # каждый элемент cur_items: (kind, payload, w, h, d, glue_left)
    cur_items: list[tuple] = []
    cur_width = 0.0

    def flush_line() -> None:
        nonlocal cur_items, cur_width
        if not cur_items:
            return
        baseline = float(asc)
        max_depth = float(desc)
        for kind, _payload, _w, h, d, _glue in cur_items:
            if kind == "math":
                baseline = max(baseline, h - d)
                max_depth = max(max_depth, d)
        line_height = baseline + max_depth
        items = []
        x = 0.0
        for i, (kind, payload, w, h, d, glue) in enumerate(cur_items):
            if i > 0 and not glue:
                x += space_w
            y_off = baseline - asc if kind == "word" else baseline - (h - d)
            items.append((x, y_off, kind, payload))
            x += w
        lines.append({"items": items, "height": line_height})
        cur_items = []
        cur_width = 0.0

    for kind, payload, glue in atoms:
        if kind == "word":
            w = draw.textlength(payload, font=body_font)
            h = float(asc + desc)
            d = float(desc)
            item_payload = payload
        else:
            try:
                img, depth = render_inline_math(payload)
            except Exception:
                log.exception("не удалось срендерить inline-формулу: %s", payload)
                kind = "word"
                item_payload = payload
                w = draw.textlength(payload, font=body_font)
                h = float(asc + desc)
                d = float(desc)
            else:
                item_payload = img
                w = img.width
                h = float(img.height)
                d = float(depth)
        gap = 0.0 if (glue or not cur_items) else space_w
        if cur_items and cur_width + gap + w > max_width:
            flush_line()
            gap = 0.0  # первый элемент новой строки — без ведущего пробела
        cur_items.append((kind, item_payload, w, h, d, glue or not cur_items))
        cur_width += gap + w
    flush_line()

    total_height = sum(int(round(l["height"])) + 10 for l in lines)
    return lines, total_height


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
    max_text_w = CARD_W - 2 * PAD

    if revealed:
        for paragraph in _split_paragraphs(back):
            chunks = [c for c in _MATH_SPLIT.split(paragraph) if c != ""]
            non_empty = [c for c in chunks if c.strip()]
            if len(non_empty) == 1 and _is_math(non_empty[0]):
                # Параграф — это ровно одна формула целиком: показываем
                # крупно и по центру (главная формула карточки).
                try:
                    img = render_latex(_unwrap_math(non_empty[0]))
                    body_blocks.append(("display", img))
                except Exception:
                    log.exception("не удалось срендерить LaTeX: %s", non_empty[0])
                    atoms = _tokenize_paragraph(paragraph)
                    lines, _h = _layout_flow(draw, atoms, body_font, max_text_w)
                    body_blocks.append(("flow", lines))
            else:
                atoms = _tokenize_paragraph(paragraph)
                if atoms:
                    lines, _h = _layout_flow(draw, atoms, body_font, max_text_w)
                    body_blocks.append(("flow", lines))
    else:
        body_blocks.append(("hidden", "формула скрыта — нажми «Показать ответ»"))

    for kind, payload in body_blocks:
        if kind == "display":
            img = payload
            y += 8
            y += img.height + 16
        elif kind == "hidden":
            y += 80
        elif kind == "flow":
            for line in payload:
                y += int(round(line["height"])) + 10
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
        if kind == "display":
            y = _paste(canvas, payload, y + 8) + 16
        elif kind == "hidden":
            draw.text((PAD, y + 24), str(payload), font=body_font, fill=MUTED)
            y += 80
        elif kind == "flow":
            for line in payload:
                line_top = y
                for x_off, y_off, item_kind, item_payload in line["items"]:
                    px = PAD + int(round(x_off))
                    py = line_top + int(round(y_off))
                    if item_kind == "word":
                        draw.text((px, py), item_payload, font=body_font, fill=INK)
                    else:
                        canvas.alpha_composite(item_payload, (px, py))
                y += int(round(line["height"])) + 10
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
