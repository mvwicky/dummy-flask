from __future__ import annotations

import mimetypes
import random
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from flask import (
    Response,
    abort,
    after_this_request,
    current_app,
    redirect,
    request,
    send_file,
)
from loguru import logger
from PIL import features

from .._types import ResponseType
from ..constants import IMG_FORMATS, IMG_FORMATS_STR, NO_CACHE
from ..fonts import fonts
from ..utils import get_count, make_rules
from . import bp
from .anim import make_anim
from .args import ImageArgs, TiledImageArgs
from .files import files
from .img import GeneratedImage
from .tiled import GeneratedTiledImage
from .utils import RAND_COLOR, random_color

WEBP_ANIM = features.check_feature("webp_anim")
ANIM_FMTS = {"gif"}.union({"webp"} if WEBP_ANIM else set())


def make_route(prefix: str = "") -> Callable:
    rule_parts = make_rules()
    rules: list[tuple[str, dict[str, Any]]] = []

    for part, defaults in rule_parts:
        rules.append((f"/<dim:size>/{part}/", defaults))

    def func(f: Callable) -> Callable:
        for rule, defaults in rules:
            bp.add_url_rule("".join((prefix, rule)), None, f, defaults=defaults)
        return f

    return func


def do_cleanup(res: ResponseType) -> ResponseType:
    n = files.clean()
    if n > 0:
        logger.info("Removed {0} file{1}", n, "" if n == 1 else "s")
    return res


def font_redirect(font_name: str) -> ResponseType:
    if font_name.lower() in fonts.font_names:
        parts = urlsplit(request.url)
        query = {**parse_qs(parts.query), "font": [font_name.lower()]}
        query_list = [(k, v) for k, v in query.items()]
        url = urlunsplit(parts._replace(query=urlencode(query_list, doseq=True)))
        return redirect(url)
    else:
        abort(400)


def check_format(fmt: str) -> str:
    fmt = fmt.lower()
    if fmt not in IMG_FORMATS:
        abort(400)
    return fmt


def get_send_file_kwargs(path: str) -> dict[str, Any]:
    mime = mimetypes.guess_type(path)[0]
    return {"mimetype": mime, "etag": not current_app.debug, "conditional": True}


@bp.route("/count/")
def count_route():
    return {"count": get_count()}


@make_route()
def image_route(
    size: tuple[int, int], bg_color: str, fg_color: str, fmt: str
) -> ResponseType:
    fmt = check_format(fmt)
    args = ImageArgs.from_request().real_args()
    if args.font_name not in fonts.font_names:
        return font_redirect(args.font_name)

    bg_lower, fg_lower = map(str.casefold, [bg_color, fg_color])
    if RAND_COLOR in {bg_lower, fg_lower}:
        random.seed(args.seed)
        if bg_lower == RAND_COLOR:
            bg_color = random_color()
        if fg_lower == RAND_COLOR:
            fg_color = random_color()

    img = GeneratedImage(size, fmt, bg_color, fg_color, args)
    path = img.get_path()
    if files.need_to_clean:
        after_this_request(do_cleanup)

    kw = get_send_file_kwargs(path)
    res: Response = send_file(path, **kw)  # type: ignore
    if args.random_text or RAND_COLOR in {bg_lower, fg_lower}:
        res.headers["Cache-Control"] = NO_CACHE
    if args.random_text:
        res.headers["X-Random-Text"] = args.text

    return res


@make_route(prefix="anim")
def anim_route(
    size: tuple[int, int], bg_color: str, fg_color: str, fmt: str
) -> Response:
    if fmt not in ANIM_FMTS:
        abort(400)
    anim = make_anim(size, bg_color, fg_color, fmt)
    print(len(anim.getvalue()))

    return send_file(anim, mimetype=f"image/{fmt}")


@bp.route("/text")
def text_route() -> str:
    return "TEXT"


@bp.route(f"/tiled/<dim:size>/<int:cols>/<int:rows>/<any({IMG_FORMATS_STR}):fmt>/")
def tiled_route(size: tuple[int, int], cols: int, rows: int, fmt: str) -> str:
    fmt = check_format(fmt)
    args = TiledImageArgs.from_request()
    img = GeneratedTiledImage(size, fmt, "0000", "0000", args, cols, rows)
    path = img.get_path()
    if files.need_to_clean:
        after_this_request(do_cleanup)

    kw = get_send_file_kwargs(path)
    res: Response = send_file(path, **kw)  # type: ignore
    res.headers["Cache-Control"] = NO_CACHE
    return res
