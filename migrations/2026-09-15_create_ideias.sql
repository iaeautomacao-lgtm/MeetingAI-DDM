CREATE TABLE IF NOT EXISTS ideias (
  id VARCHAR(36) PRIMARY KEY,
  titulo VARCHAR(180) NOT NULL,
  setor VARCHAR(120) NOT NULL,
  dor TEXT NOT NULL,
  solucao TEXT NOT NULL,
  impacto VARCHAR(120) NOT NULL,
  autor_nome VARCHAR(180) NOT NULL DEFAULT '',
  autor_email VARCHAR(180) NOT NULL DEFAULT '',
  ai_titulo VARCHAR(180) DEFAULT '',
  ai_problema TEXT,
  ai_proposta TEXT,
  ai_potencial TEXT,
  impactos_possiveis LONGTEXT,
  ai_primeiro_passo TEXT,
  score INT NOT NULL DEFAULT 60,
  status VARCHAR(40) NOT NULL DEFAULT 'nova',
  criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  atualizado_em DATETIME NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP
);

CREATE INDEX idx_ideias_setor ON ideias (setor);
CREATE INDEX idx_ideias_impacto ON ideias (impacto);
CREATE INDEX idx_ideias_score ON ideias (score);
CREATE INDEX idx_ideias_criado_em ON ideias (criado_em);
CREATE INDEX idx_ideias_status ON ideias (status);
