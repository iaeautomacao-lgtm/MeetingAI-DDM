ALTER TABLE painel_acessos
ADD COLUMN IF NOT EXISTS is_gestor TINYINT(1) NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_painel_acessos_is_gestor
ON painel_acessos (is_gestor);

CREATE INDEX IF NOT EXISTS idx_reunioes_solicitante
ON reunioes (solicitante);
