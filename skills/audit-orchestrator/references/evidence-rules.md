# The evidence gate

The rubric rewards few misses **and** few false positives. Recall is cheap;
precision is what makes an audit trustworthy. This gate is how precision is
enforced.

## The rule

> A finding may be emitted only if it can quote a literal artifact from the
> probe evidence. No artifact, no finding.

An artifact is one of:

- an HTTP status code **together with the user-agent that produced it**
- a count **together with its denominator** (`8/12 pages`)
- a tag, attribute or property name that is present or absent
- a URL
- a verbatim string from the page

Not artifacts: "the site seems slow", "content feels thin", "the brand is not
well known", "competitors do this better". Those are opinions. If the probes did
not measure it, the audit does not claim it.

## Applying it during step 6 of the entrypoint procedure

For every finding, open the evidence file it came from and confirm the artifact
exists and says what the finding says. Then choose:

| Outcome | Action |
|---|---|
| Artifact confirms the claim | Keep it. |
| Artifact exists but is weaker than the claim | Reword the claim down to the artifact. |
| Artifact is missing or contradicts | **Delete the finding.** |
| Real signal, but the fix is speculative | Move to `proactive_recommendations`. |

Deleting a finding is a success, not a loss.

## Known false positives, and how each is handled

These are the traps a naive checklist walks into. Each is already mitigated in
the rules; the notes say how, so a reviewer can confirm the reasoning.

| Signal | Why it misleads | Mitigation in this marketplace |
|---|---|---|
| Missing `<h1>` | Some templates use an image logo as the visual heading | Reported at medium; de-escalated when isolated |
| Thin text | The page may be a legitimate index or redirect stub | `F-RND-002` excludes pages already reported as SPA shells, so the same page is never counted twice |
| Overlay class names | A class named `modal` may never render | Confidence `medium`, evidence says static analysis cannot confirm |
| Two brand names | Often a legitimate parent org and its site | Confidence `medium`; the fix explains `parentOrganization` rather than assuming sloppiness |
| Missing canonical | Harmless on a site with no duplicate URLs | Medium, blast-radius adjusted |
| Stale copyright year | May be a genuine legal notice frozen on purpose | Severity `low`, never escalated |
| `noindex` | May be deliberate on a staging or thin page | Reported, but the fix says "on pages that should be findable" |
| Missing `llms.txt` | Not a standard, and not universally consumed | Severity `low`, framed as an opportunity |
| Blocked training bots | A legitimate policy choice, not a defect | Framed as "confirm this is deliberate", never as an error |
| No `sameAs` | The probe sees only what the site declares | Evidence states what was measured, not that off-site presence is absent |

## The sampling caveat

Every count is over the **sampled** pages, not the whole site. Findings say
`8/12 sampled pages`, never `the whole site`. If the sample is under 3 pages,
say so and stop generalizing from it.
