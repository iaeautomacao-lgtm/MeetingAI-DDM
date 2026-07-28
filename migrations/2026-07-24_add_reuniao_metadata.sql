set search_path to meeting_ai;

alter table reunioes add column if not exists modalidade text default 'online';
alter table reunioes add column if not exists local_reuniao text default '';
alter table reunioes add column if not exists cliente text default '';
