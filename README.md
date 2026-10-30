# state-seed

One-time refill for the hosted site's saved state (`.state`), used by `.github/workflows/website.yml`
only when a build starts without it: snapshot history (rebuilt from the live site's heatmap data,
Oct 25-30 2026) and the briefings archive. Files already in `.state` are never overwritten.
