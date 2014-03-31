drop table if exists shows;
create table shows (
    id integer primary key autoincrement,
    name text not null,
    forum_url text not null,
    tvdb_id integer not null
);