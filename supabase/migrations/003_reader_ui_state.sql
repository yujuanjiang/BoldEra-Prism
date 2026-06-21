alter table public.source_items
  add column if not exists user_status text not null default 'unread',
  add column if not exists saved boolean not null default false,
  add column if not exists user_note text,
  add column if not exists last_seen_at timestamptz;

create index if not exists source_items_user_status_idx
  on public.source_items (user_status);

create index if not exists source_items_saved_idx
  on public.source_items (saved);
