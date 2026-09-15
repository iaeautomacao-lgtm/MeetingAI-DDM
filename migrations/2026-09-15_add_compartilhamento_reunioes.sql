ALTER TABLE reunioes
  ADD COLUMN IF NOT EXISTS compartilhado_setores LONGTEXT NULL,
  ADD COLUMN IF NOT EXISTS compartilhado_emails LONGTEXT NULL;
