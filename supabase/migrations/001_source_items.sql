create table if not exists public.source_items (
  id bigserial primary key,
  source text not null,
  topic_id text not null,
  external_id text not null,
  url text not null,
  title text not null,
  author text,
  community text,
  published_at timestamptz,
  collected_at timestamptz not null,
  score integer,
  comment_count integer,
  raw_text text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (source, external_id)
);

create index if not exists source_items_topic_id_idx
  on public.source_items (topic_id);

create index if not exists source_items_source_idx
  on public.source_items (source);

create index if not exists source_items_published_at_idx
  on public.source_items (published_at desc);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists source_items_set_updated_at on public.source_items;

create trigger source_items_set_updated_at
before update on public.source_items
for each row
execute function public.set_updated_at();
