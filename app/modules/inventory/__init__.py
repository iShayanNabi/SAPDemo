"""Module 7 - Inventory Predictor.

Reads historical inventory and demand movements, forecasts future demand with
explainable statistical models, projects the resulting stock level forward and
recommends reorder actions.

**No AI model produces a number here.** Every forecast, confidence interval,
shortage date, reorder quantity, safety stock figure and stock classification is
computed by ordinary Python in :mod:`forecasting`, :mod:`selection`,
:mod:`accuracy` and :mod:`projection`. The optional AI narrative in
:mod:`ai_narrative` only rephrases results the engine has already decided, in
separate fields that never overwrite a computed value.

The five forecasting methods are deliberately the explainable ones - a planner
can reproduce any of them in a spreadsheet:

* simple moving average
* weighted moving average
* simple exponential smoothing
* Holt's linear trend
* Holt-Winters additive seasonal model (only when two full seasons exist)

Which one is used per material/plant is decided by :mod:`selection`, which
backtests every eligible method on a held-out tail of the real history and picks
the winner on the configured error metric.
"""
