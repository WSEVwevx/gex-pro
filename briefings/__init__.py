"""Session briefings for GEX PRO: a NY AM briefing before the US open and an Asia briefing for the night session.

Independent like every feature package: it never imports gexsys or feeds. The app shell (gexpro) gives
it a plain snapshot of the current data (see compose.py for the shape), the market calendar and a
notifier; this package decides when a briefing is due, writes it, and keeps a short history.
"""
