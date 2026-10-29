import os
import logging
from aiohttp import web

logger = logging.getLogger("health_server")

async def health_endpoint(request: web.Request):
    """
    Health check endpoint supporting both GET and HEAD requests.
    Returns 200 OK JSON for /health or /ping.
    """
    data = {
        "status": "ok",
        "service": "Numbott",
        "message": "Bot is healthy and running"
    }
    return web.json_response(data, status=200)

async def root_endpoint(request: web.Request):
    """
    Root endpoint supporting both GET and HEAD requests.
    Used by UptimeRobot, Render health checks, etc.
    """
    return web.Response(
        text="OK - Numbott is running!",
        status=200,
        content_type="text/plain"
    )

def create_health_app() -> web.Application:
    app = web.Application()
    # Explicit routes for GET, HEAD, and any HTTP method
    app.router.add_route("*", "/", root_endpoint)
    app.router.add_route("*", "/health", health_endpoint)
    app.router.add_route("*", "/ping", root_endpoint)
    # Catch-all route so ANY path requested by uptime monitoring returns 200 OK
    app.router.add_route("*", "/{tail:.*}", root_endpoint)
    return app

async def start_health_server():
    """
    Starts lightweight aiohttp web server on PORT (default 8080 or env PORT).
    Designed specifically for Render, Railway, Heroku and UptimeRobot pings.

    Never raises: if the preferred port is taken the next one is tried, and a
    total failure is only logged.  A health-check problem must not stop the bot.
    """
    port_str = os.environ.get(
        "BOT_HEALTH_PORT",
        os.environ.get("PORT", os.environ.get("HTTP_PORT", "8080")),
    )
    try:
        port = int(port_str)
    except (TypeError, ValueError):
        port = 8080

    host = "0.0.0.0"
    app = create_health_app()
    runner = web.AppRunner(app, handle_signals=False)

    try:
        await runner.setup()
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f"\u26a0\ufe0f Health server setup failed: {e}")
        return None

    # Try the requested port, then a few nearby ones.  A busy port (common on
    # shared hosts that already run a proxy) used to leave the app with no
    # health endpoint at all, so the platform marked it unhealthy.
    candidates = [port] + [p for p in (8080, 8000, 8888, 5000, 3000) if p != port]
    for candidate in candidates:
        try:
            site = web.TCPSite(runner, host, candidate)
            await site.start()
            logger.info(
                f"\U0001F310 Health server started on http://{host}:{candidate} "
                "(Supports GET & HEAD)"
            )
            return runner
        except OSError as e:
            logger.warning(f"Port {candidate} unavailable ({e}); trying next...")
        except Exception as e:  # pragma: no cover - defensive
            logger.error(f"\u26a0\ufe0f Could not bind health server on port {candidate}: {e}")

    logger.error("\u26a0\ufe0f Health server could not bind any port \u2014 bot continues without it.")
    try:
        await runner.cleanup()
    except Exception:
        pass
    return None
