import functools
from typing import Optional, Text

from flask import current_app, request

from .. import redis_client
from .._types import Dimension
from ..utils import make_rules
from . import bp
from .utils import make_image


@functools.lru_cache()
def image_response(
    size: Dimension,
    bg_color: Text,
    fg_color: Text = "#000",
    fmt: Text = "png",
    text: Optional[Text] = None,
    filename: Optional[Text] = None,
    font_name: Optional[Text] = None,
):
    cache_time = current_app.config.get("MAX_AGE", 0)
    im = make_image(size, bg_color, fg_color, fmt, text, font_name)
    if filename is None:
        filename = "img-{0}-{1}.{2}".format(
            "x".join(map(str, size)), bg_color.replace("#", ""), fmt
        )
    if not filename.endswith("." + fmt):
        filename = ".".join([filename, fmt])
    return (
        im.getvalue(),
        {
            "Content-Type": f"image/{fmt}",
            "Cache-Control": f"public, max-age={cache_time}",
        },
    )


def make_route():
    rule_parts = make_rules()
    rules = list()

    for part, defaults in rule_parts:
        rule = "/<dim:size>/" + part + "/"
        rules.append((rule, defaults))

    def func(f):
        for rule, defaults in rules:
            bp.add_url_rule(rule, None, f, defaults=defaults)
        return f

    return func


@make_route()
def image_route(size, bg_color, fg_color, fmt):
    redis_client.incr("image_count")
    text = request.args.get("text", None)
    filename = request.args.get("filename")
    font_name = request.args.get("font")
    return image_response(
        size,
        bg_color,
        fg_color,
        fmt,
        text=text,
        filename=filename,
        font_name=font_name,
    )
