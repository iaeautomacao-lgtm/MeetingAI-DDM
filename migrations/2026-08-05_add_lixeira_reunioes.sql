-- Lixeira de reuniões: exclusão lógica com retenção de 30 dias.
-- MariaDB 10.11 (cPanel).
--
-- ATENÇÃO: só ADD COLUMN. Nunca dropar nem re-rodar schema completo nesta
-- base — foi assim que as tabelas foram zeradas em 10/07/2026 (STATUS 3.4).

ALTER TABLE reunioes
  ADD COLUMN IF NOT EXISTS excluida_em  DATETIME     NULL DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS excluida_por VARCHAR(190) NULL DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_reunioes_excluida_em ON reunioes (excluida_em);
