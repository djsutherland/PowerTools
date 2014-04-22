drop table if exists shows;
create table shows (
    id integer primary key autoincrement,
    name text not null,
    forum_id integer not null,
    forum_topics integer,
    forum_posts integer,
    tvdb_ids text not null,
    gone_forever boolean not null default 0,
    we_do_ep_posts boolean not null default 1
);

drop table if exists mods;
create table mods (
    id integer primary key autoincrement,
    name text not null
);

drop table if exists turfs;
create table turfs (
    showid integer references shows(id) on update cascade on delete cascade,
    modid integer references mods(id) on update cascade on delete cascade,
    state text not null,
    comments text not null,
    PRIMARY KEY (showid, modid)
);
