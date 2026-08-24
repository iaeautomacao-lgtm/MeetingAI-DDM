ALTER TABLE painel_acessos
ADD COLUMN IF NOT EXISTS is_gestor TINYINT(1) NOT NULL DEFAULT 0;

ALTER TABLE painel_acessos
ADD COLUMN IF NOT EXISTS perfil_solicitado VARCHAR(20) NOT NULL DEFAULT 'usuario';

CREATE INDEX IF NOT EXISTS idx_painel_acessos_is_gestor
ON painel_acessos (is_gestor);

CREATE INDEX IF NOT EXISTS idx_painel_acessos_perfil_solicitado
ON painel_acessos (perfil_solicitado);

CREATE INDEX IF NOT EXISTS idx_reunioes_solicitante
ON reunioes (solicitante);
