# NM i AI 2026 - Tripletex Challenge Overview

## What Is This?

An AI agent competition where you build a system that completes accounting operations in Tripletex via its REST API. Part of the Norwegian AI Championship (NM i AI 2026), running March 19-22, with 1,000,000 NOK total prize pool across three challenges.

## How It Works

1. You submit an HTTPS endpoint URL to the platform (`app.ainm.no`)
2. A **fresh Tripletex sandbox account** is provisioned for each submission (you always start from scratch)
3. A randomly selected accounting task is POSTed to your `/solve` endpoint
4. Your agent interprets the natural-language prompt and executes the necessary Tripletex API calls
5. Results are verified field-by-field against expected outcomes
6. Scores update on a rolling leaderboard

## Key Numbers

| Parameter | Value |
|-----------|-------|
| Task types | 30 |
| Variants per task | 56 (7 languages x 8 datasets) |
| Languages | Norwegian, English, Spanish, Portuguese, Nynorsk, German, French |
| Timeout per submission | 5 minutes (300 seconds) |
| Score range per task | 0.0 - 6.0 |
| Max theoretical total score | 30 x 6.0 = 180.0 |

## Task Categories

- Employee management (creation, roles, contact updates)
- Customer and product registration
- Invoicing and payment processing
- Travel expense reports
- Project creation and linking
- Ledger corrections and reversals
- Department setup and module enablement

## Tier System & Release Schedule

| Tier | Multiplier | Status | Examples |
|------|-----------|--------|----------|
| Tier 1 | x1 | Open | Create employee, customer |
| Tier 2 | x2 | Open | Create invoice, register payment |
| Tier 3 | x3 | Opens early Saturday | Complex multi-step workflows (bank reconciliation, ledger corrections, year-end closing) |

## Rate Limits

| Limit | Verified Teams | Unverified Teams |
|-------|---------------|-----------------|
| Concurrent submissions | 3 | 1 |
| Per task per day | 10 | 3 |

## Infrastructure

Selected verified teams receive free GCP accounts with:
- Cloud Run (recommended for hosting the endpoint)
- Vertex AI with Gemini models
- No credit limits

## Leaderboard

- **Total score** = sum of best scores across all 30 task types
- Your all-time best score per task is kept - bad runs never lower scores
- Best score per task is recalculated against current benchmarks every 12 hours
