---
title: Command-Line Interface
---

## Example

This example generates data containing all Statistics Department courses in the Gateway building for Fall '26 that start at 6pm and later.

```{code} shell
:label: Example 1

cardgate courses \
    --unit STAT --building Gateway \
    --year 2026 --semester Fall --from-time 18:00 \
    --output stat-gateway-2026-fall.csv
```
