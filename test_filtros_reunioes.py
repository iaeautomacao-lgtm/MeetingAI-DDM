import unittest
from datetime import datetime
from unittest.mock import patch

from app import create_app


class CursorFiltrosFake:
    def __init__(self, rows=None, fetches=None):
        self.sql = ""
        self.params = []
        self.rows = rows or []
        self.fetches = list(fetches or [])
        self.executions = []

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = list(params or [])
        self.executions.append((sql, list(params or [])))

    def fetchall(self):
        if self.fetches:
            return self.fetches.pop(0)
        return self.rows

    def close(self):
        return None


class ConnectionFiltrosFake:
    def __init__(self, rows=None, fetches=None):
        self.cursor_fake = CursorFiltrosFake(rows, fetches)

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
                "&usuario=Gisele%20Oliveira%20(gisele.oliveira%40ddm.adv.br)"
                "&cliente=cruzeiro&local=Sede%20RJ"
            )

        self.assertEqual(resposta.status_code, 200)
        self.assertIn("LOWER(COALESCE(solicitante", connection.cursor_fake.sql)
        self.assertIn("LOWER(COALESCE(cliente", connection.cursor_fake.sql)
        self.assertIn("local_reuniao = %s", connection.cursor_fake.sql)
        self.assertIn("LIMIT 200", connection.cursor_fake.sql)
        self.assertIn("2026-09-22 23:59:59", connection.cursor_fake.params)
        self.assertIn("%gisele oliveira%", connection.cursor_fake.params)
        self.assertIn("%gisele.oliveira@ddm.adv.br%", connection.cursor_fake.params)
        self.assertIn("%cruzeiro%", connection.cursor_fake.params)
        self.assertIn("Sede RJ", connection.cursor_fake.params)

    @patch("app.api.routes._escopo_reunioes_sql", return_value=(" AND setor = %s", ["IA"]))
    def test_opcoes_de_filtro_vem_do_banco_respeitando_escopo(self, _escopo):
        connection = ConnectionFiltrosFake(fetches=[[
            {
                "data": datetime(2026, 9, 22, 9, 15),
                "cliente": "Cliente A",
                "local_reuniao": "Sede RJ",
            },
            {
                "data": "2026-09-21 14:30:00",
                "cliente": "Cliente B",
                "local_reuniao": "Online",
            },
        ]])
        with patch("app.api.routes.get_mysql_connection", return_value=connection):
            client = self.app.test_client()
            with client.session_transaction() as sessao:
                sessao["diretor"] = True
                sessao["acesso_total"] = True

            resposta = client.get("/api/reunioes/filtros")

        self.assertEqual(resposta.status_code, 200)
        payload = resposta.get_json()
        self.assertEqual(payload["datas"], ["2026-09-22", "2026-09-21"])
        self.assertEqual(payload["usuarios"], [])
        self.assertEqual(payload["clientes"], ["Cliente A", "Cliente B"])
        self.assertEqual(payload["locais"], ["Online", "Sede RJ"])
        self.assertIn("AND setor = %s", connection.cursor_fake.executions[0][0])
        self.assertEqual(connection.cursor_fake.executions[0][1], ["IA"])


if __name__ == "__main__":
    unittest.main()
