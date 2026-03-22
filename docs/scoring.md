# Scoring System

## Overview

Each task score has three components:

```
task_score = correctness * tier_multiplier * (1 + efficiency_bonus)
```

Maximum possible per task: **6.0** (on Tier 3 with perfect efficiency).

## 1. Correctness (0.0 - 1.0)

Field-by-field verification against expected values. Each task has specific checks worth different point values.

**Example: "Create employee" task**

| Check | Points |
|-------|--------|
| Employee found | 2 |
| Correct first name | 1 |
| Correct last name | 1 |
| Correct email | 1 |
| Administrator role | 5 |
| **Total** | **10** |

**Formula:** `correctness = points_earned / max_points`

Example: 8/10 = 0.8 correctness

## 2. Tier Multiplier

| Tier | Multiplier |
|------|-----------|
| Tier 1 | x1 |
| Tier 2 | x2 |
| Tier 3 | x3 |

Applied directly to correctness: `base_score = correctness * multiplier`

## 3. Efficiency Bonus (only on perfect correctness)

**Only unlocked when correctness = 1.0.** Can potentially **double** the tier score.

Two factors:
- **Call efficiency:** Number of API calls compared to best-known solution (fewer = higher bonus)
- **Error cleanliness:** Number of 4xx errors (400, 404, 422) reduces the bonus

### Tier 2 Examples

| Scenario | Score |
|----------|-------|
| Failed all checks | 0.0 |
| 80% checks passed | 1.6 |
| Perfect, many errors | ~2.1 |
| Perfect, efficient, few errors | ~2.6 |
| Perfect, best efficiency, zero errors | 4.0 |

## Benchmark Recalculation

- Efficiency benchmarks are recalculated periodically
- As teams find more efficient solutions, the bar rises for everyone
- Your best score per task is recalculated against current benchmarks **every 12 hours**

## Leaderboard

- **Total score** = sum of best scores across all 30 task types
- All-time best per task is kept - subsequent submissions cannot lower scores
- Each of the 30 tasks tracks independently
