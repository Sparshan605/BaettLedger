-- BaettLedger schema — v2, zone-based architecture (Aug 13 rewrite)
-- Source: docs/api.md §5. The beam sensor is gone. One session now produces
-- TWO photos of a single capture — 'wide' (counted) and 'closeup'
-- (cross-check) — each of which may show several device types at once.
--
-- Run this against a FRESH database only. It drops nothing itself, but
-- run_schema.py drops every table before applying it, so never point that at a
-- database with real data in it. To change an existing database, write a
-- migration instead — migrate_zones.py is the worked example.

CREATE TABLE session (
    session_id     NVARCHAR(64)  PRIMARY KEY,
    device_id      NVARCHAR(64)  NOT NULL,
    session_type   NVARCHAR(3)   NOT NULL CHECK (session_type IN ('OUT','IN')),
    session_date   DATE          NOT NULL,
    opened_at      DATETIME2     NOT NULL,
    closed_at      DATETIME2     NULL,
    status         NVARCHAR(10)  NOT NULL DEFAULT 'open'
);

-- One row per PHOTO now, not one row per device. zone tells you which capture
-- this is: 'wide' is the counted one, 'closeup' the cross-check.
-- device_type/count no longer live here — see count_detection below, since one
-- photo can hold several device types.
--
-- left/middle/right/overview are the retired three-zone design. They stay
-- permitted so rows captured before Aug 13 remain valid; db.COUNT_ZONES is what
-- decides which of them are added to a total.
CREATE TABLE count_event (
    event_id     INT IDENTITY(1,1) PRIMARY KEY,
    session_id   NVARCHAR(64) NOT NULL REFERENCES session(session_id),
    device_id    NVARCHAR(64) NOT NULL,
    sequence     INT          NOT NULL,   -- 1-2 within the session
    zone         NVARCHAR(10) NOT NULL
        CONSTRAINT ck_event_zone CHECK
            (zone IN ('wide','closeup','left','middle','right','overview')),
    captured_at  DATETIME2    NOT NULL,   -- Pi clock
    received_at  DATETIME2    NOT NULL DEFAULT SYSUTCDATETIME(),  -- server clock, trust this one
    photo_url    NVARCHAR(400) NULL,
    analyzed_at  DATETIME2     NULL,      -- NULL until Vision + Agent have run
    confidence   DECIMAL(4,3)  NULL,
    needs_review BIT           NOT NULL DEFAULT 0,
    reason       NVARCHAR(400) NULL,
    confirmed_by NVARCHAR(100) NULL,
    confirmed_at DATETIME2     NULL,
    CONSTRAINT uq_event UNIQUE (device_id, session_id, sequence)
);

-- What was found IN one photo. One row per device type, so a zone holding
-- three cones and a sign is two rows against the same event.
CREATE TABLE count_detection (
    detection_id INT IDENTITY(1,1) PRIMARY KEY,
    event_id     INT          NOT NULL REFERENCES count_event(event_id),
    device_type  NVARCHAR(20) NOT NULL
        CHECK (device_type IN ('cone','sign','barricade','delineator','unknown')),
    count        INT          NOT NULL,
    CONSTRAINT uq_detection UNIQUE (event_id, device_type)
);

CREATE TABLE daily_total (
    total_date   DATE         NOT NULL,
    device_type  NVARCHAR(20) NOT NULL,
    out_total    INT NOT NULL DEFAULT 0,
    in_total     INT NOT NULL DEFAULT 0,
    difference   INT NOT NULL DEFAULT 0,
    PRIMARY KEY (total_date, device_type)
);

CREATE INDEX ix_event_session ON count_event(session_id);
CREATE INDEX ix_event_review  ON count_event(needs_review) WHERE needs_review = 1;
