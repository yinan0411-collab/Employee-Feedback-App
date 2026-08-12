-- Employee Feedback & Recognition - Supabase schema
-- Run this once in Supabase > SQL Editor.

create extension if not exists pgcrypto;

create table if not exists public.employees (
    employee_id text primary key,
    erp text,
    name text not null,
    attendance_group text,
    employment_status text,
    account_status text,
    department text,
    job text,
    employment_type text,
    vendor text,
    hire_date date,
    termination_date date,
    raw_data jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
);

create table if not exists public.feedback_records (
    id uuid primary key default gen_random_uuid(),
    employee_id text not null references public.employees(employee_id) on delete restrict,
    record_date date not null,
    feedback_type text not null check (feedback_type in ('Feedback', 'Verbal Warning', 'Written Warning', 'Final Warning')),
    content text not null,
    note text,
    created_by text,
    created_at timestamptz not null default now()
);

create table if not exists public.recognition_records (
    id uuid primary key default gen_random_uuid(),
    employee_id text not null references public.employees(employee_id) on delete restrict,
    record_date date not null,
    content text not null,
    note text,
    created_by text,
    created_at timestamptz not null default now()
);

create index if not exists idx_employees_attendance_group on public.employees(attendance_group);
create index if not exists idx_employees_status on public.employees(employment_status);
create index if not exists idx_feedback_employee on public.feedback_records(employee_id);
create index if not exists idx_feedback_record_date on public.feedback_records(record_date desc);
create index if not exists idx_recognition_employee on public.recognition_records(employee_id);
create index if not exists idx_recognition_record_date on public.recognition_records(record_date desc);

-- Security note:
-- The Streamlit app uses a server-side Supabase Secret Key (sb_secret_...) stored
-- only in Streamlit Secrets. Secret keys bypass RLS and must never be committed to GitHub.
-- RLS is enabled here so public/anonymous clients cannot read or modify these tables.
alter table public.employees enable row level security;
alter table public.feedback_records enable row level security;
alter table public.recognition_records enable row level security;
