# Data dictionary

Generated from the schemas in `datapulse/sources/`. Do not edit by hand —
run `datapulse dictionary` instead.

## How to use this data

- One row is a single observation, not a summary. Stacking the daily files gives you one long table, which is the shape most tools expect.
- A missing day means the source did not report that day. It does not mean zero, and it does not mean the value was unchanged.
- Do not fill those gaps by carrying values forward or averaging neighbours. That invents numbers nobody published, and once written they cannot be told apart from real ones.
- If you need a continuous series, aggregate upwards instead. Grouping by state, or nationally, has far fewer gaps than a single market does.
- Use series_id to follow one thing across days. It is derived from the identifying columns, so it is the same code in every run.
- Rows that failed a quality check are kept, not deleted, with the reason in quality_flag. Filter to an empty quality_flag for clean rows only.

## `mandi_prices`

- **Domain:** food_mandi
- **Grain:** one row per state + district + market + commodity + variety + grade + arrival_date per market_date
- **One series is:** state + district + market + commodity + variety + grade
- **Files are named after:** `market_date`

| Column | Type | Unit | Empty means | Description |
|---|---|---|---|---|
| `collected_date` | datetime64[ns] | — | never empty | When our robot fetched the row. Provenance, not a market date. |
| `market_date` | datetime64[ns] | — | the portal gave an unreadable arrival_date | The trading day these prices are for. Files are named after this. |
| `series_id` | string | — | one of the six identifying fields was missing | Stable code for one market + crop + variety + grade. Use it to follow the same thing across days. |
| `state` | string | — | not reported | State or union territory, spelled as the portal spells it. |
| `district` | string | — | not reported | District within the state. |
| `market` | string | — | not reported | The mandi (wholesale market) reporting the price. |
| `commodity` | string | — | never empty | The crop or product traded. |
| `variety` | string | — | not reported | Variety of the commodity, e.g. Local, Nasik, Jyoti. |
| `grade` | string | — | not reported | Quality grade. The same crop at one market trades at several grades with genuinely different prices. |
| `arrival_date` | string | — | not reported | Trading day exactly as the portal sent it (DD/MM/YYYY). market_date is the parsed version. |
| `min_price` | float64 | INR per quintal (100 kg) | not reported | Lowest price recorded at that market that day. |
| `max_price` | float64 | INR per quintal (100 kg) | not reported | Highest price recorded at that market that day. |
| `modal_price` | float64 | INR per quintal (100 kg) | not reported | The most common price that day. Usually the one to use. |
| `source` | string | — | never empty | Which pipeline collected the row. |
| `quality_flag` | string | — | the row passed all checks | Empty when the row passed every check. Otherwise a comma-separated list of what looked wrong. Flagged rows are kept, never deleted. |
