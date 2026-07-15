-- Rode no SQL Editor do Supabase (projeto meeting_ai).
set search_path to meeting_ai;

-- coluna que marca admin direto no banco (gerenciável pelo painel, sem mexer em código)
alter table painel_acessos add column if not exists is_admin boolean default false;

-- (opcional) já deixar joao.dimaio como admin caso ele já esteja cadastrado:
update painel_acessos set is_admin = true where email = 'joao.dimaio@ddm.adv.br';

select email, nome, setor, is_admin, aprovado from painel_acessos order by criado_em desc;
