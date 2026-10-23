"""Track record and backtest: how GEX PRO's levels held up against what the market actually did.

  score.py      the plan (levels frozen before the 09:30 ET open) and the rules that grade it after the close
  prices.py     free daily and intraday index prices (Cboe, Yahoo) and implied-vol index history (Cboe)
  backtest.py   the historical expected-move backtest from VIX / VXN (decades of data)
  component.py  the GEX PRO component: storage, schedule, /api/trackrecord, hosted data files

Independent of the other packages: the app shell hands it the pre-open levels (see gexpro/context.py).
"""
