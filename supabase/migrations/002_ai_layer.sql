create table if not exists public.source_item_analyses (
  id bigserial primary key,
  source_item_id bigint not null references public.source_items(id) on delete cascade,
  topic_id text not null,
  model text not null,
  summary text not null,
  highlights jsonb not null default '[]'::jsonb,
  claims jsonb not null default '[]'::jsonb,
  tools_mentioned jsonb not null default '[]'::jsonb,
  tags jsonb not null default '[]'::jsonb,
  difficulty text,
  learning_value integer,
  follow_up_questions jsonb not null default '[]'::jsonb,
  raw_response jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (source_item_id)
);

create index if not exists source_item_analyses_topic_id_idx
  on public.source_item_analyses (topic_id);

create table if not exists public.topic_comparisons (
  id bigserial primary key,
  topic_id text not null,
  model text not null,
  source_item_ids bigint[] not null default '{}'::bigint[],
  shared_points jsonb not null default '[]'::jsonb,
  controversial_points jsonb not null default '[]'::jsonb,
  unique_points jsonb not null default '[]'::jsonb,
  learning_path jsonb not null default '[]'::jsonb,
  open_questions jsonb not null default '[]'::jsonb,
  raw_response jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists topic_comparisons_topic_id_idx
  on public.topic_comparisons (topic_id);

drop trigger if exists source_item_analyses_set_updated_at on public.source_item_analyses;

create trigger source_item_analyses_set_updated_at
before update on public.source_item_analyses
for each row
execute function public.set_updated_at();
