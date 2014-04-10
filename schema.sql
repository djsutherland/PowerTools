drop table if exists shows;
create table shows (
    id integer primary key autoincrement,
    name text not null,
    forum_url text not null,
    forum_topics integer,
    forum_posts integer,
    tvdb_id integer not null,
    gone_forever boolean not null default 0,
    we_do_ep_posts boolean not null default 1
);