-- Runs once, the first time the Postgres container starts.

CREATE TABLE links (
    code       text PRIMARY KEY,
    url        text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    clicks     bigint NOT NULL DEFAULT 0
);

-- "Recent links" in the UI reads newest first.
CREATE INDEX links_created_at_idx ON links (created_at DESC);

-- Each API replica takes a block of 1000 ids per trip (see ids.py): nextval jumps by 1000.
CREATE SEQUENCE link_id_blocks INCREMENT BY 1000 START WITH 0 MINVALUE 0;
