-- ============================================================================
-- Portfolio Intelligence Engine — Paper Trading tables migration
-- Bead: OpenBBTechnical-qy83.1.5
-- PRD:  docs/Specs/Portfolio-Intelligence-Engine-PRD.md §16.3
-- ============================================================================
--
-- SCOPE
--   Creates five paper_* tables backing the Paper Trading Engine (PRD §16).
--   These live SIDE-BY-SIDE with Portfolio_Positions / portfolio_basket but
--   are STRICTLY ISOLATED from them — no foreign keys, no shared columns,
--   no cross-namespace joins ever. Every table carries user_id so the app
--   can filter without joining and cross-account isolation (bead
--   OpenBBTechnical-qy83.4.12, SEV-1) is enforceable in query alone.
--
-- APPLY / ROLLBACK
--   Apply:    mysql -u <user> -p <db> < 001_paper_trading.sql
--   Rollback: DROP TABLE paper_ledger, paper_positions, paper_fills,
--             paper_orders, paper_accounts;   -- (child-first order)
--
-- M0 EXIT CRITERIA
--   File exists, syntactically valid MySQL, structural contract enforced by
--   portfolio_app/tests/test_paper_migration.py. NOT applied until bead
--   OpenBBTechnical-qy83.4.8 in P2.
--
-- CHARSET / COLLATION
--   utf8mb4 across every table — matches openbb_platform/providers/
--   fmp_cached/create_mysql_setup.sql so international company / holder
--   names round-trip cleanly.
-- ============================================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;
SET SQL_MODE = 'STRICT_ALL_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE';

-- ----------------------------------------------------------------------------
-- paper_accounts — one row per paper account per user
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS paper_accounts (
    account_id           VARCHAR(64)  NOT NULL,
    user_id              VARCHAR(64)  NOT NULL,
    display_name         VARCHAR(120) NULL,
    starting_cash        DECIMAL(18, 4) NOT NULL,
    cash_balance         DECIMAL(18, 4) NOT NULL,
    currency             CHAR(3)      NOT NULL DEFAULT 'USD',
    margin_enabled       TINYINT(1)   NOT NULL DEFAULT 0,
    commission_model     VARCHAR(32)  NOT NULL DEFAULT 'zero',
    slippage_bps         INT          NOT NULL DEFAULT 5,
    is_active            TINYINT(1)   NOT NULL DEFAULT 1,
    created_at           TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
                                        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (account_id),
    UNIQUE KEY uq_paper_accounts_user_account (user_id, account_id),
    KEY ix_paper_accounts_user (user_id, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- paper_orders — order lifecycle rows
--   status ENUM covers all six PRD §16.3 states.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS paper_orders (
    order_id             CHAR(36)     NOT NULL,   -- UUID string
    account_id           VARCHAR(64)  NOT NULL,
    user_id              VARCHAR(64)  NOT NULL,
    symbol               VARCHAR(20)  NOT NULL,
    side                 ENUM('buy', 'sell', 'sell_short', 'buy_to_cover') NOT NULL,
    qty                  DECIMAL(18, 6) NOT NULL,
    order_type           ENUM('market', 'limit', 'stop', 'stop_limit', 'trailing_stop') NOT NULL,
    limit_price          DECIMAL(18, 4) NULL,
    stop_price           DECIMAL(18, 4) NULL,
    trail_amount         DECIMAL(18, 4) NULL,
    time_in_force        ENUM('day', 'gtc', 'ioc', 'fok') NOT NULL,
    status               ENUM('open', 'filled', 'partial', 'cancelled', 'rejected', 'expired') NOT NULL DEFAULT 'open',
    submitted_at         TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    filled_at            TIMESTAMP    NULL,
    avg_fill_price       DECIMAL(18, 4) NULL,
    filled_qty           DECIMAL(18, 6) NOT NULL DEFAULT 0,
    rejection_reason     TEXT         NULL,
    PRIMARY KEY (order_id),
    KEY ix_paper_orders_account_status (account_id, status),
    KEY ix_paper_orders_account_symbol (account_id, symbol),
    KEY ix_paper_orders_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- paper_fills — one row per (partial) execution
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS paper_fills (
    fill_id              CHAR(36)     NOT NULL,   -- UUID string
    order_id             CHAR(36)     NOT NULL,
    account_id           VARCHAR(64)  NOT NULL,
    user_id              VARCHAR(64)  NOT NULL,
    symbol               VARCHAR(20)  NOT NULL,
    qty                  DECIMAL(18, 6) NOT NULL,
    price                DECIMAL(18, 4) NOT NULL,
    commission           DECIMAL(18, 4) NOT NULL DEFAULT 0,
    slippage_applied_bps INT          NOT NULL DEFAULT 0,
    quote_snapshot_id    VARCHAR(64)  NULL,       -- ref to fmp_cached quote row for replay
    filled_at            TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (fill_id),
    KEY ix_paper_fills_order (order_id),
    KEY ix_paper_fills_account_time (account_id, filled_at),
    KEY ix_paper_fills_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- paper_positions — derived from fills, persisted for widget latency
--   Signed quantity: negative = short.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS paper_positions (
    account_id           VARCHAR(64)  NOT NULL,
    user_id              VARCHAR(64)  NOT NULL,
    symbol               VARCHAR(20)  NOT NULL,
    quantity             DECIMAL(18, 6) NOT NULL,   -- signed
    avg_cost             DECIMAL(18, 4) NOT NULL,
    realized_pnl         DECIMAL(18, 4) NOT NULL DEFAULT 0,
    updated_at           TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
                                        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (account_id, symbol),
    KEY ix_paper_positions_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- paper_ledger — APPEND-ONLY cash + corporate-action journal
--   PRD §16.7 replay contract: no updated_at, monotonic entry_id, occurred_at
--   for ordering. Every state change of any account is materialised here.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS paper_ledger (
    entry_id             CHAR(36)     NOT NULL,   -- UUID string
    account_id           VARCHAR(64)  NOT NULL,
    user_id              VARCHAR(64)  NOT NULL,
    entry_type           ENUM('trade', 'dividend', 'split', 'fee', 'deposit', 'withdraw') NOT NULL,
    symbol               VARCHAR(20)  NULL,
    amount               DECIMAL(18, 4) NOT NULL,
    occurred_at          TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes                VARCHAR(255) NULL,
    PRIMARY KEY (entry_id),
    KEY ix_paper_ledger_account_time (account_id, occurred_at),
    KEY ix_paper_ledger_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET FOREIGN_KEY_CHECKS = 1;

-- ============================================================================
-- End of 001_paper_trading.sql
-- ============================================================================
