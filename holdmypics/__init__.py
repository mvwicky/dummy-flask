import sys
import time
from pathlib import Path

from flask import Flask, request, send_from_directory
from flask_redis import FlaskRedis
from funcy import memoize
from loguru import logger

from config import Config
from .converters import ColorConverter, DimensionConverter
from .wrapped_redis import WrappedRedis

redisw = WrappedRedis()
redis_client = FlaskRedis()

HERE: Path = Path(__file__).resolve().parent


CACHE_CONTROL_MAX = "max-age=315360000, public, immutable"


@memoize
def get_version() -> str:
    from .__version__ import __version__

    return __version__


def config_logging():
    logger.remove()
    fmt = (
        "[<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green>] | <level>{level:<8}</level> | "
        "<blue>{name}</blue>:<cyan>{line}</cyan> - <bold>{message}</bold>"
    )
    logger.add(sys.stderr, format=fmt)
    log_dir = HERE.parent / "log"
    if log_dir.is_dir():
        log_file = log_dir / (__name__ + ".log")
        logger.add(
            log_file,
            rotation=10 * 1024,
            level="DEBUG",
            filter=__name__,
            compression="tar.gz",
            retention=5,
        )


def create_app(config_class=Config):
    config_logging()

    app = Flask(__name__)
    app.config.from_object(config_class)

    hsts_seconds = app.config.get("HSTS_SECONDS", 0)
    hsts_preload = app.config.get("HSTS_PRELOAD", False)
    if hsts_seconds:
        parts = [
            f"max-age={hsts_seconds}",
            "includeSubDomains",
            "preload" if hsts_preload else False,
        ]
        HSTS_HEADER = "; ".join(filter(bool, parts))
    else:
        HSTS_HEADER = None

    app.url_map.redirect_defaults = False
    app.url_map.converters.update({"dim": DimensionConverter, "col": ColorConverter})

    redisw.init_app(app, redis_client)

    from . import core

    app.register_blueprint(core.bp)

    from . import api

    app.register_blueprint(api.bp, url_prefix="/api")

    from . import cli

    cli.register(app)

    @app.before_request
    def before_request_cb():
        request.start_time = time.monotonic()

    @app.after_request
    def after_request_cb(res):
        endpoint = request.endpoint
        if endpoint == "core.index":
            res.headers["Cache-Control"] = "max-age=0, no-store"
        elif endpoint == "static":
            name = request.path.split("/")[-1]
            parts = name.split(".")
            if len(parts) == 3:
                res.headers["Cache-Control"] = CACHE_CONTROL_MAX

        if HSTS_HEADER is not None:
            res.headers["Strict-Transport-Security"] = HSTS_HEADER
        res.headers["X-Powered-By"] = "Flask"
        elapsed = time.monotonic() - request.start_time
        res.headers["X-Processing-Time"] = elapsed

        return res

    @app.route("/favicon.ico")
    def _favicon_route():
        return send_from_directory(app.root_path, "fav.ico")

    @app.context_processor
    def _ctx():
        return {"version": get_version()}

    logger.info("Created App {0!r}", app)
    return app
