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
    """
    port_str = os.environ.get(
        "BOT_HEALTH_PORT",
        os.environ.get("PORT", os.environ.get("HTTP_PORT", "8080")),
    )
    try:
        port = int(port_str)
    except ValueError:
        port = 8080

    host = "0.0.0.0"
    app = create_health_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)

    try:
        await site.start()
        logger.info(f"🌐 Health server started on http://{host}:{port} (Supports GET & HEAD)")
    except Exception as e:
        logger.error(f"⚠️ Could not bind health server on port {port}: {e}")

    return runner
