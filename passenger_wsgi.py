"""
Entry point para cPanel / Phusion Passenger ("Setup Python App").
O Passenger procura a variável `application`. Aponta para o app Flask.

Obs: no cPanel NÃO se usa gunicorn/Procfile (isso é do Railway) — o Passenger
gerencia o processo. As variáveis de ambiente são definidas na UI do
"Setup Python App" (seção Environment variables).
"""

from run import app as application
