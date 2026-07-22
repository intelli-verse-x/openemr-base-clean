# Contract migration notes

## v1 (current)

Initial schemas published under `contracts/v1/`:

- `campaign_plan.schema.json`
- `attack_result.schema.json`
- `verdict.schema.json`
- `vuln_report.schema.json`
- `errors.schema.json`

## Rules

1. Additive optional fields → stay on `v1`, document here.  
2. Removing/renaming required fields → bump to `v2/`, update producers/consumers + contract tests.  
3. Exploit store (`adversarial/store/exploits.jsonl`): new fields must be optional or backfilled; never drop `exploit_id`.

## History

| Date | Change |
|------|--------|
| 2026-07-21 | v1 published with platform MVP |
| 2026-07-23 | No breaking changes; added regression harness reading v1 store rows |
