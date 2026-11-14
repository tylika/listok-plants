-- =====================================================================
-- Листок: таблиця «Мої рослини» + сховище мініатюр у Supabase
-- Як виконати: Supabase -> SQL Editor -> New query -> вставити весь файл -> Run
-- Скрипт можна запускати повторно: він нічого не зламає.
-- =====================================================================

create table if not exists public.plants (
  id               uuid primary key default gen_random_uuid(),
  created_at       timestamptz not null default now(),
  common_name      text not null,
  latin_name       text not null default '',
  family           text not null default '',
  confidence       smallint not null default 0 check (confidence between 0 and 100),
  health_status    text not null default 'unknown' check (health_status in ('healthy', 'problems', 'unknown')),
  has_problems     boolean not null default false,
  is_toxic_to_pets boolean not null default false,
  result           jsonb not null,          -- повна JSON-відповідь Gemini (поради, проблеми, токсичність)
  model            text not null default '',
  latency_ms       integer not null default 0,
  cost_usd         numeric(12, 6),          -- приблизна вартість запиту на платному рівні
  thumb_path       text,                    -- шлях до мініатюри в Storage
  thumb_url        text                     -- публічне посилання на мініатюру
);

create index if not exists plants_created_at_idx on public.plants (created_at desc);

-- Row Level Security: доступ з браузера напряму заборонено.
-- Сервер працює із секретним ключем (secret / service_role), який обходить RLS.
alter table public.plants enable row level security;

-- Публічний bucket для мініатюр (480 px, ~30–60 КБ кожна).
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('plant-thumbs', 'plant-thumbs', true, 2097152, array['image/jpeg'])
on conflict (id) do update set public = true;

-- Зручне представлення для статистики (можна показати викладачу в Table Editor).
create or replace view public.plants_stats
with (security_invoker = on) as
select
  count(*)                                   as total,
  count(*) filter (where has_problems)       as with_problems,
  count(*) filter (where is_toxic_to_pets)   as toxic_to_pets,
  round(avg(latency_ms))                     as avg_latency_ms,
  round(sum(coalesce(cost_usd, 0)), 6)       as total_cost_usd
from public.plants;
