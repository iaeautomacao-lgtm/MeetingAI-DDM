"""
Entry point para a Vercel (Python Serverless Functions).
A Vercel serve o app WSGF exposto na variável `app`.
Todas as rotas são redirecionadas para cá pelo vercel.json.
"""

from run import app  # noqa: F401  (a Vercel detecta e serve `app`)
