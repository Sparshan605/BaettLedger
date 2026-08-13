-- BaettLedger schema — run this against sql-baettledger (Basic tier), db name "baettledger"
-- Source: docs/api.md §5. Run this on Aug 14 before writing any events.

CREATE TABLE session (
    session_id     NVARCHAR(64)  PRIMARY KEY,
    device_id      NVARCHAR(64)  NOT NULL,
    session_type   NVARCHAR(3)   NOT NULL CHECK (session_type IN ('OUT','IN')),
    session_date   DATE          NOT NULL,
    opened_at      DATETIME2     NOT NULL,
    closed_at      DATETIME2     NULL,
    status         NVARCHAR(10)  NOT NULL DEFAULT 'open'
);

CREATE TABLE count_event (
    event_id     INT IDENTITY(1,1) PRIMARY KEY,
    session_id   NVARCHAR(64) NOT NULL REFERENCES session(session_id),
    device_id    NVARCHAR(64) NOT NULL,
    sequence     INT          NOT NULL,
    captured_at  DATETIME2    NOT NULL,   -- Pi clock
    received_at  DATETIME2    NOT NULL DEFAULT SYSUTCDATETIME(),  -- server clock, trust this one
    photo_url    NVARCHAR(400) NULL,
    device_type  NVARCHAR(20) NULL,       -- NULL until Vision runs
    count        INT           NULL,
    confidence   DECIMAL(4,3)  NULL,
    needs_review BIT           NOT NULL DEFAULT 0,
    reason       NVARCHAR(400) NULL,
    confirmed_by NVARCHAR(100) NULL,
    confirmed_at DATETIME2     NULL,
    CONSTRAINT uq_event UNIQUE (device_id, session_id, sequence)
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
