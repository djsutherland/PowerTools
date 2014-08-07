drop table if exists shows;
create table shows (
    id integer primary key autoincrement,
    name text not null,
    forum_id integer not null,
    forum_topics integer,
    forum_posts integer,
    tvdb_ids text not null,
    gone_forever boolean not null default 0,
    we_do_ep_posts boolean not null default 1,
    eps_up_to_snuff boolean not null default 0,
    needs_leads boolean not null default 0,
    needs_backups boolean not null default 0
);

drop table if exists show_genres;
create table show_genres (
    showid integer references shows(id) on update cascade on delete cascade,
    seriesid integer not null,
    genre text not null,
    PRIMARY KEY (seriesid, genre)
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

drop table if exists episodes;
create table episodes (
    id integer primary key,
    seasonid integer,
    seriesid integer,
    showid integer references shows(id) on update cascade on delete cascade,
    season_number text,
    episode_number text,
    name text,
    overview text,
    first_aired text
);

drop table if exists meta;
create table meta (
    name text primary key,
    value text
);


drop table if exists bingo;
create table bingo (
    id integer primary key,
    name text,
    row integer not null,
    col integer not null,
    unique(row, col)
);

drop table if exists mod_bingo;
create table mod_bingo (
    bingoid integer references bingo(id) on update cascade on delete cascade,
    modid integer references mods(id) on update cascade on delete cascade,
    PRIMARY KEY (bingoid, modid)
);
