CREATE TABLE IF NOT EXISTS senha_resets (
  id CHAR(36) PRIMARY KEY,
  email VARCHAR(255) NOT NULL,
  codigo_hash VARCHAR(255) NOT NULL,
  expira_em DATETIME NOT NULL,
  usado_em DATETIME NULL,
  criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_senha_resets_email (email),
  INDEX idx_senha_resets_expira (expira_em)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
