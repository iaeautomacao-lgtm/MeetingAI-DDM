import os

os.environ["SESSION_COOKIE_SECURE"] = "0"

from app import create_app


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5003"))
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
