import unittest
from unittest.mock import patch

from app import create_app


class CursorFake:
    def execute(self, _sql, _params=None):
        return None

    def fetchall(self):
        return [
            {
                "id": "r1",
                "titulo": "Reunião ao vivo",
                "setor": "IA",
                "data": "2026-09-18T15:00:00",
                "recall_bot_id": "b1",
            },
            {
                "id": "r2",
                "titulo": "Reunião agendada",
                "setor": "Financeiro",
                "data": "2026-09-21T08:00:00",
                "recall_bot_id": "b2",
            },
        ]

    def close(self):
        return None


class ConnectionFake:
    def cursor(self, dictionary=False):
        return CursorFake()

    def is_connected(self):
        return True

    def close(self):
        return None


class CapacidadeBotsTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, SECRET_KEY="teste")

    @patch("app.pipeline.skribby_client.get_bot")
    @patch("app.api.routes.get_mysql_connection", return_value=ConnectionFake())
    def test_conta_apenas_status_ativos(self, _connection, get_bot):
        get_bot.side_effect = lambda bot_id: {
            "status": "recording" if bot_id == "b1" else "scheduled"
        }
        client = self.app.test_client()
        with client.session_transaction() as sessao:
            sessao["diretor"] = True
            sessao["acesso_total"] = True

        resposta = client.get("/api/bots/capacidade")
        dados = resposta.get_json()

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(dados["limite_simultaneo"], 25)
        self.assertEqual(dados["ativos"], 1)
        self.assertEqual(dados["vagas_disponiveis"], 24)
        self.assertEqual(dados["agendados"], 1)


if __name__ == "__main__":
    unittest.main()
