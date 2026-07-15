-- Rode no SQL Editor do Supabase (projeto meeting_ai).
set search_path to meeting_ai;

-- 1) coluna de setor no acesso do painel (travada no cadastro; só admin troca)
alter table painel_acessos add column if not exists setor text default '';

-- 2) setor dos admins (opcional — admins já têm acesso total de qualquer forma)
update painel_acessos set setor = 'Diretores' where email in
  ('gisele.oliveira@ddm.adv.br', 'dimaio@ddm.adv.br');

-- 3) defina o setor de quem já está cadastrado (exemplos — ajuste):
-- update painel_acessos set setor = 'Comercial'  where email = 'fulano@ddm.adv.br';
-- update painel_acessos set setor = 'Financeiro' where email = 'ciclana@ddm.adv.br';

-- Confira:
select email, nome, setor, aprovado from painel_acessos order by criado_em desc;
