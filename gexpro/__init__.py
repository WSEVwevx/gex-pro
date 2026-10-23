"""GEX PRO app shell: plugs the feature packages into one website.

  python -m gexpro serve --auto                     the local website + background work (START.bat)
  python -m gexpro build-site --out _site --state .state   the hosted copy (GitHub workflow)

The shell owns no market logic. Each feature package provides a component (see components.py):
  gexsys  -> GexComponent    options GEX levels, the hourly TradingView paste, the indicator script
  feeds   -> FeedsComponent  ForexFactory calendar, Truth Social posts
  briefings -> BriefingsComponent  NY AM and Asia session briefings (reads a snapshot from gexpro/context.py)
"""
