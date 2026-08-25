# Data collection ethics & legal posture

This project publishes an open dataset, so collection has to be defensible.

**Rules the code enforces**
- A real, identifying User-Agent with a contact route (`Settings.user_agent`).
- `robots.txt` is honoured by default (`respect_robots_txt: true`).
- Conservative per-source rate limits; exponential backoff with jitter on 429/5xx.

**Rules you enforce when adding a source**
1. Prefer official APIs and open-government portals over scraping HTML.
2. Read the site's Terms of Service. If redistribution is forbidden, set
   `publishable = False` — collect for analysis, don't commit the raw rows.
3. Collect **aggregates and listing attributes**, never personal data: no seller
   names, phone numbers, emails, or exact addresses. If a field could identify a
   person, drop it in `parse`, not later.
4. Keep volume proportionate — sample, don't mirror the site.
5. Honour takedown requests; document the source URL and licence in the module docstring.

**If a site asks you to stop:** set `enabled: false`, open an issue recording the
request, and leave the historical data decision to the requester.
