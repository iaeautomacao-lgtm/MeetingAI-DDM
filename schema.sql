-- ============================================================================
-- MEETING AI — Schema Supabase (Postgres)
-- Inferido do uso no código (app/workers/tasks.py, app/api/routes.py).
-- Rodar no Supabase: SQL Editor → colar → Run.
-- ============================================================================

create extension if not exists "pgcrypto";  -- gen_random_uuid()

-- Schema dedicado (projeto compartilhado ddm lab). Depois: expor "meeting_ai"
-- em Project Settings → API → Exposed schemas.
create schema if not exists meeting_ai;
set search_path to meeting_ai;

-- ── Usuários (Azure AD) ─────────────────────────────────────────────────────
create table if not exists usuarios (
    id            uuid primary key default gen_random_uuid(),
    ms_user_id    text unique not null,
    nome          text default '',
    email         text,
    setor         text default '',
    cargo         text default '',
    ativo         boolean default true,
    atualizado_em timestamptz default now()
);
create index if not exists idx_usuarios_ativo on usuarios (ativo);
create index if not exists idx_usuarios_setor on usuarios (setor);

-- ── Setores ─────────────────────────────────────────────────────────────────
create table if not exists setores (
    id    uuid primary key default gen_random_uuid(),
    nome  text not null,
    cor   text default '#6366f1',
    ativo boolean default true
);

-- ── Reuniões ────────────────────────────────────────────────────────────────
create table if not exists reunioes (
    id                uuid primary key default gen_random_uuid(),
    ms_meeting_id     text unique,
    recall_bot_id     text,                       -- id do bot Recall.ai (plataforma=recall)
    titulo            text default 'Reunião',
    setor             text default '',
    data              timestamptz,
    plataforma        text default 'teams',      -- teams | recall | avulso
    status            text default 'pending',     -- pending|processing|completed|sem_transcricao|error
    transcricao_full  text,
    utterances        jsonb default '[]'::jsonb,
    duracao_minutos   integer,
    topicos           jsonb default '[]'::jsonb,
    decisoes          jsonb default '[]'::jsonb,
    pendencias        jsonb default '[]'::jsonb,
    resumo_executivo  text default '',
    sentimento_geral  text default 'neutro',
    participantes     jsonb default '[]'::jsonb,
    erro_msg          text,
    criado_em         timestamptz default now()
);
create index if not exists idx_reunioes_status     on reunioes (status);
create index if not exists idx_reunioes_data       on reunioes (data desc);
create index if not exists idx_reunioes_setor      on reunioes (setor);
create index if not exists idx_reunioes_plataforma on reunioes (plataforma);
create index if not exists idx_reunioes_recall_bot on reunioes (recall_bot_id);

-- Se a tabela reunioes JÁ existe no Supabase (caso do projeto ddm lab), rode:
--   set search_path to meeting_ai;
--   alter table reunioes add column if not exists recall_bot_id text;
--   create index if not exists idx_reunioes_recall_bot on reunioes (recall_bot_id);

-- ── E-mails ─────────────────────────────────────────────────────────────────
create table if not exists emails (
    id               uuid primary key default gen_random_uuid(),
    message_id       text unique,
    de_email         text,
    de_nome          text default '',
    para             jsonb default '[]'::jsonb,
    assunto          text default '',
    setor_remetente  text default '',
    data             timestamptz,
    thread_id        text,
    plataforma       text default 'outlook',
    status           text default 'pending',     -- pending|completed|error
    resumo           text default '',
    temas            jsonb default '[]'::jsonb,
    sentimento       text default 'neutro',
    categoria        text default 'corporativo',  -- corporativo|promocional|notificacao|spam|pessoal
    relevante        boolean default true,
    erro_msg         text,
    criado_em        timestamptz default now()
);
create index if not exists idx_emails_categoria on emails (categoria);
create index if not exists idx_emails_relevante on emails (relevante);
create index if not exists idx_emails_status  on emails (status);
create index if not exists idx_emails_data    on emails (data desc);
create index if not exists idx_emails_setor   on emails (setor_remetente);
create index if not exists idx_emails_sentim  on emails (sentimento);

-- ── Interações (grafo pessoa↔pessoa por tema) ───────────────────────────────
-- upsert usa on_conflict="pessoa_a,pessoa_b,tema" → precisa constraint única.
create table if not exists interacoes (
    id               uuid primary key default gen_random_uuid(),
    pessoa_a         text not null,
    pessoa_b         text not null,
    tema             text not null,
    contagem         integer default 1,
    ultima_interacao timestamptz default now(),
    constraint uq_interacao unique (pessoa_a, pessoa_b, tema)
);
create index if not exists idx_interacoes_contagem on interacoes (contagem desc);

-- ── Resumos diários ─────────────────────────────────────────────────────────
-- upsert usa on_conflict="data" → coluna data única.
create table if not exists resumos_diarios (
    id             uuid primary key default gen_random_uuid(),
    data           date unique not null,
    total_reunioes integer default 0,
    total_emails   integer default 0,
    destaques      jsonb default '[]'::jsonb,
    alertas        jsonb default '[]'::jsonb,
    resumo_texto   text default '',
    criado_em      timestamptz default now()
);

-- ── Seed opcional de setores ────────────────────────────────────────────────
insert into setores (nome, cor) values
    ('Comercial',   '#6366f1'),
    ('Financeiro',  '#10b981'),
    ('Operações',   '#f59e0b'),
    ('TI',          '#3b82f6'),
    ('RH',          '#ec4899'),
    ('Jurídico',    '#ef4444'),
    ('Diretoria',   '#8b5cf6')
on conflict do nothing;
