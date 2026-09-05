# Severity model

Severity is **derived**, never chosen. Two auditors running this marketplace on
the same site must produce the same severities.

```
severity = base(funnel_stage, hard_block?)  adjusted by  blast_radius
```

## Step 1 — base, from the stage that broke

| Stage | What it means | Base |
|---|---|---|
| `accessible` | Crawler is refused. Nothing downstream can be true. | **critical** if a citation-family crawler is refused, else high |
| `discovered` | Crawler is allowed but cannot find the page | high if `noindex`, else medium |
| `renderable` | Page fetched, but content is not in the HTML | **critical** if content requires JS site-wide, else high |
| `extractable` | Content is readable but not machine-parseable or quotable | high |
| `corroborated` | Fact is readable but undated, unattributed or unverifiable | high if no date signal at all, else medium |
| `selected` | Content exists but is not shaped for retrieval | medium |
| `retained` | Discovery worked; the visitor left anyway | high if the fact is unreachable, else medium |

The ordering encodes the actual mechanism: earlier stages gate later ones, so a
break there costs more.

## Step 2 — blast radius

Measured as *affected pages ÷ pages sampled*.

| Ratio | Adjustment |
|---|---|
| ≥ 0.8 | escalate one level — this is how the site is built, not an oversight |
| 0.26 – 0.79 | no change |
| ≤ 0.25 | de-escalate one level — isolated, likely a single bad template |

If fewer than 3 pages were sampled, skip step 2 entirely and keep the base. A
ratio computed from two pages is noise wearing a number's clothes.

## Step 3 — blocked_by

Any finding at `renderable` or later is tagged `blocked_by` when a **critical
`accessible`** finding exists. Tagged findings keep their severity — they are
real — but the report leads with the blocker, because fixing anything else first
cannot be verified.

## Step 4 — confidence, which is not severity

Severity is how much it costs. Confidence is how sure we are.

- **high** — a status code, a count with a denominator, a parsed tag, a URL.
- **medium** — a heuristic that can be wrong: overlay class names, brand-name
  variants, "looks like a product page" path matching. Must name what to verify.

A medium-confidence finding is still reported. It is never silently promoted to
high, and never presented as certain.

## Worked example

`F-RND-001`, JS render gap, on 4 of 4 sampled pages:
base `renderable` + site-wide → **critical**; ratio 1.0 → escalate → capped at
critical. On 1 of 12 pages: base high, ratio 0.08 → de-escalate → **medium**.
Same rule, same evidence shape, different blast radius, defensible either way.
