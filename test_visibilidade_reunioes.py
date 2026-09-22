import unittest
from unittest.mock import patch

from app.api import routes


class VisibilidadeReunioesTest(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch.object(routes, "tem_acesso_total", return_value=False),
            patch.object(routes, "is_gestor_setor", return_value=False),
            patch.object(routes, "sessao_email", return_value="pessoa@ddm.adv.br"),
            patch.object(routes, "sessao_setores", return_value=["Financeiro"]),
            patch.object(routes, "_solicitantes_sessao", return_value=["pessoa@ddm.adv.br", "pessoa"]),
            patch.object(routes, "_tem_coluna_reunioes", return_value=True),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def reuniao(self, visibilidade="gestores", **outros):
        return {
            "setor": "Financeiro",
            "solicitante": "outra pessoa",
            "compartilhado_setores": [],
            "compartilhado_emails": [],
            "visibilidade_setor": visibilidade,
            **outros,
        }

    def test_usuario_comum_ve_reuniao_aberta_do_setor(self):
        self.assertTrue(routes._pode_acessar_reuniao(self.reuniao("todos")))

    def test_usuario_comum_nao_ve_reuniao_reservada_nem_por_email(self):
        reuniao = self.reuniao(compartilhado_emails=["pessoa@ddm.adv.br"])
        self.assertFalse(routes._pode_acessar_reuniao(reuniao))

    def test_criador_ve_reuniao_reservada(self):
        reuniao = self.reuniao(solicitante="pessoa@ddm.adv.br")
        self.assertTrue(routes._pode_acessar_reuniao(reuniao))

    def test_gestor_ve_reuniao_reservada_do_setor(self):
        with patch.object(routes, "is_gestor_setor", return_value=True):
            self.assertTrue(routes._pode_acessar_reuniao(self.reuniao()))

    def test_escopo_sql_aplica_a_mesma_restricao(self):
        sql, params = routes._escopo_reunioes_sql()
        self.assertIn("visibilidade_setor = 'todos'", sql)
        self.assertIn("setor IN", sql)
        self.assertIn("Financeiro", params)


if __name__ == "__main__":
    unittest.main()
