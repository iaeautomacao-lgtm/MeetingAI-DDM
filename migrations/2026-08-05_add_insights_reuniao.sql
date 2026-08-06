-- Blocos de insight gerados pela IA em cada reunião.
-- MariaDB 10.11 (cPanel).
--
-- ATENÇÃO: só ADD COLUMN. Nunca dropar nem re-rodar schema completo nesta
-- base — foi assim que as tabelas foram zeradas em 10/07/2026 (STATUS 3.4).

ALTER TABLE reunioes
  ADD COLUMN IF NOT EXISTS key_takeaways     TEXT NULL,
  ADD COLUMN IF NOT EXISTS riscos            TEXT NULL,
  ADD COLUMN IF NOT EXISTS perguntas_abertas TEXT NULL,
  ADD COLUMN IF NOT EXISTS clima             TEXT NULL;
