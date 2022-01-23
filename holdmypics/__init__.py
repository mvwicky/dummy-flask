import re
import sys
import time
from functools import lru_cache, partial
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union, cast

from flask import Flask, Response, g, request, send_from_directory
from loguru import logger
from whitenoise import WhiteNoise

from .converters import ColorConverter, DimensionConverter
from .log_config import config_logging, log_request, log_static_file
from .wrapped_redis import WrappedRedis

if TYPE_CHECKING:
    from types import ModuleType
    from wsgiref.headers import Headers

redisw = WrappedRedis()

HERE: Path = Path(__file__).resolve().parent

REQUEST_TIMER = time.perf_counter

CACHE_CONTROL_MAX = "max-age=315360000, public, immutable"
PY_VERSION = ".".join(map(str, sys.version_info[:3]))

_exts = ("woff", "woff2", "js", "css")
_exts_group = "|".join("".join((e[::-1], ".")) for e in _exts)
EXT_RE = re.compile("^(?:{0})".format(_exts_group))


@lru_cache(maxsize=2)
def get_powered_by(inc_whitenoise: bool) -> str:
    python_version = "/".join(("Python", PY_VERSION))
    flask_version = "/".join(("Flask", version("flask")))
    parts = [python_version, flask_version]
    if inc_whitenoise:
        parts.append("/".join(("Whitenoise", version("whitenoise"))))
    return ", ".join(parts)


def wn_add_headers(version: str, headers: "Headers", path: str, url: str):
    log_static_file(path, url)
    headers["X-Powered-By"] = get_powered_by(True)
    headers["X-Version"] = version


def immutable_file_test(debug: bool, path: str, url: str) -> bool:
    if debug:
        return False
    parts = url.rsplit("/", 1)
    if len(parts) == 1:
        return False
    filename: str = parts[1]
    is_immutable = filename.count(".") > 1 and bool(EXT_RE.match(filename[::-1]))
    if is_immutable:
        logger.debug("File is immutable: {0}", url)
    return is_immutable


def configure_hsts(app: Flask):
    hsts_seconds = app.config.get("HSTS_SECONDS", 0)
    hsts_preload = app.config.get("HSTS_PRELOAD", False)
    include_sub = app.config.get("HSTS_INCLUDE_SUBDOMAINS", False)
    if hsts_seconds:
        parts = [
            "max-age={0}".format(hsts_seconds),
            "includeSubDomains" if include_sub else False,
            "preload" if hsts_preload else False,
        ]
        return "; ".join(filter(bool, parts))
    else:
        return None


def before_request_callback():
    g.start_time = REQUEST_TIMER()


def after_request_callback(
    hsts_header: Optional[str], version: str, res: Response
) -> Response:
    log_request(res)
    endpoint = request.endpoint
    if endpoint == "web.index":
        res.headers["Cache-Control"] = "max-age=0, no-store"
    elif endpoint == "static":
        name = request.path.split("/")[-1]
        parts = name.split(".")
        if len(parts) == 3:
            res.headers["Cache-Control"] = CACHE_CONTROL_MAX

    if hsts_header is not None:
        res.headers["Strict-Transport-Security"] = hsts_header
    forwarded = request.headers.get("X-Forwarded-For", None)
    if forwarded is not None:
        res.headers["X-Was-Forwarded-For"] = forwarded
    res.headers["X-Powered-By"] = get_powered_by(False)
    res.headers["X-Version"] = version
    start_time = g.pop("start_time", None)
    if start_time is not None:
        elapsed = REQUEST_TIMER() - start_time
        res.headers["X-Processing-Time"] = elapsed
    return res


def format_attrs_ctx() -> dict[str, Any]:
    from .utils import format_attrs, format_attrs_kw

    return {"format_attrs": format_attrs, "format_attrs_kw": format_attrs_kw}


class Holdmypics(Flask):
    pass


def create_app(cfg: Union[str, "ModuleType"] = "config") -> Holdmypics:
    app = Holdmypics(__name__)
    app.config.from_object(cfg)
    config_logging(app)

    HSTS_HEADER = configure_hsts(app)

    app.url_map.redirect_defaults = False
    converters = {"dim": DimensionConverter, "col": ColorConverter}
    app.url_map.converters.update(converters)

    redisw.init_app(app)

    from . import api, cli, web
    from .__version__ import __version__

    app.register_blueprint(web.bp)
    app.register_blueprint(api.bp, url_prefix="/api")
    cli.register(app)

    base_path = cast(Path, app.config.get("BASE_PATH"))

    debug: bool = cast(bool, app.config.get("DEBUG"))
    app.wsgi_app = WhiteNoise(
        app.wsgi_app,
        autorefresh=True,
        add_headers_function=partial(wn_add_headers, __version__),
        immutable_file_test=partial(immutable_file_test, debug),
    )

    app.wsgi_app.add_files(str(HERE / "static"), prefix="static/")
    app.wsgi_app.add_files(str(base_path / "static"), prefix="static/")

    if debug:
        from werkzeug.debug import DebuggedApplication

        app.wsgi_app = DebuggedApplication(app.wsgi_app, evalex=True)

    _favicon = partial(send_from_directory, app.root_path, "fav.ico")
    _version_ctx = partial(dict, version=__version__)

    app.before_request(before_request_callback)
    app.after_request(partial(after_request_callback, HSTS_HEADER, __version__))
    app.add_url_rule("/favicon.ico", "favicon", _favicon)
    app.context_processor(_version_ctx)
    app.context_processor(format_attrs_ctx)

    @app.template_filter("log")
    def _log_filter(inp: Any) -> str:
        logger.info("{0!r}", inp)
        return ""

    from .utils import format_attrs

    app.template_filter("fmt_attrs")(format_attrs)

    return app
