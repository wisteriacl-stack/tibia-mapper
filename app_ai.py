from __future__ import annotations

from app import app
from ai_routes import register_ai_routes
from map_routes import register_map_routes

register_ai_routes(app)
register_map_routes(app)


@app.after_request
def inject_ai_ui(response):
    content_type = str(response.headers.get("Content-Type") or "")
    if "text/html" not in content_type:
        return response

    try:
        html = response.get_data(as_text=True)
    except Exception:
        return response

    marker = "</body>"
    script = '<script src="/static/ai_ui.js"></script>'
    if marker in html and script not in html:
        response.set_data(html.replace(marker, f"{script}\n{marker}", 1))
        response.headers["Content-Length"] = len(response.get_data())
    return response


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
