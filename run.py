import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    # Debugger do Werkzeug = execução de código remota. Só em desenvolvimento.
    debug = os.getenv("FLASK_ENV", "production").strip().lower() == "development"
    app.run(debug=debug)
