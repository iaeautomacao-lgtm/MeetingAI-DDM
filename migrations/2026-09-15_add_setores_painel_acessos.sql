ALTER TABLE painel_acessos
ADD COLUMN IF NOT EXISTS setores TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_painel_acessos_setor
ON painel_acessos (setor);
