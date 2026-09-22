ALTER TABLE reunioes
  ADD COLUMN IF NOT EXISTS visibilidade_setor VARCHAR(20) NOT NULL DEFAULT 'gestores';

CREATE INDEX IF NOT EXISTS idx_reunioes_visibilidade_setor
  ON reunioes (visibilidade_setor);
