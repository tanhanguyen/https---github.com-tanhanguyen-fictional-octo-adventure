-- Plan 14: chart snapshots. The breakout range that produced a trade is only known at
-- signal time (`Signal.range_high/range_low`, in-memory); snapshotting it onto the trade
-- row is what lets a snapshot rendered long after the fact (on-demand, or a restart)
-- redraw the same range band without reconstructing `breakout_state` history (which is
-- overwritten every tick, not versioned per trade). NULL for mean-reversion trades.
ALTER TABLE trade ADD COLUMN range_high REAL;
ALTER TABLE trade ADD COLUMN range_low REAL;
