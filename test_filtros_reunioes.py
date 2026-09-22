import unittest
from unittest.mock import patch

from app import create_app


class CursorFiltrosFake:
    def __init__(self):
        self.sql = ""
        self.params = []

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = list(params or [])

    def fetchall(self):
        return []

    def close(self):
        return None


class ConnectionFiltrosFake:
    def __init__(self):
        self.cursor_fake = CursorFiltrosFake()

    def cursor(self, dictionary=False):
        return self.cursor_fake

    def is_connected(self):
        return True

    def close(self):
        return None


class FiltrosReunioesTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, SECRET_KEY="teste")

    @patch("app.api.routes._escopo_reunioes_sql", return_value=("", []))
    def test_aplica_periodo_usuario_cliente_e_local(self, _escopo):
        connection = ConnectionFiltrosFake()
        with patch("app.api.routes.get_mysql_connection", return_value=connection):
            client = self.app.test_client()
            with client.session_transaction() as sessao:
                sessao["diretor"] = True
                sessao["acesso_total"] = True

            resposta = client.get(
                "/api/reunioes?de=2026-09-01&ate=2026-09-22"
                "&usuario=gisele&cliente=cruzeiro&local=Sede%20RJ"
            )

        self.assertEqual(resposta.status_code, 200)
        self.assertIn("LOWER(COALESCE(solicitante", connection.cursor_fake.sql)
        self.assertIn("LOWER(COALESCE(cliente", connection.cursor_fake.sql)
        self.assertIn("local_reuniao = %s", connection.cursor_fake.sql)
        self.assertIn("LIMIT 200", connection.cursor_fake.sql)
        self.assertIn("2026-09-22 23:59:59", connection.cursor_fake.params)
        self.assertIn("%gisele%", connection.cursor_fake.params)
        self.assertIn("%cruzeiro%", connection.cursor_fake.params)
        self.assertIn("Sede RJ", connection.cursor_fake.params)


if __name__ == "__main__":
    unittest.main()
