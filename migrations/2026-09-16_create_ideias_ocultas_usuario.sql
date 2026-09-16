CREATE TABLE IF NOT EXISTS ideias_ocultas_usuario (
  id VARCHAR(36) PRIMARY KEY,
  ideia_id VARCHAR(36) NOT NULL,
  usuario_email VARCHAR(180) NOT NULL,
  criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_ideias_ocultas_usuario (ideia_id, usuario_email),
  INDEX idx_ideias_ocultas_usuario_email (usuario_email),
  CONSTRAINT fk_ideias_ocultas_usuario_ideia
    FOREIGN KEY (ideia_id) REFERENCES ideias (id)
    ON DELETE CASCADE
);
