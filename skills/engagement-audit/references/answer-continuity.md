# Answer-continuity

## Who actually arrives

Not a browser. Someone an assistant already answered, clicking to **confirm one
specific fact**. They have no navigational context — they teleported into the
middle of a journey. They are pre-qualified and high-intent, which cuts both
ways: they are more likely to convert, and far less patient with a page that
makes them start over.

So the defect to hunt is not "the UX could be better". It is the **distance
between the sentence the assistant quoted and the sentence on your page**. That
is measurable.

## The three measurable components

**1. Deep-linkability.** Without stable heading `id`s, an assistant can cite
`/product` but never `/product#specs`. The visitor lands on top of a long page
and hunts for the line they were promised.

```html
<h2 id="pricing">Pricing</h2>
<h2 id="specifications">Specifications</h2>
<h2 id="availability">Availability</h2>
```

Cheapest high-value fix in this skill. Two rules: make the ids semantic, not
generated hashes; and never rename them in a redesign. Once assistants cite an
anchor, it is an address other people depend on — treat it like an API.

**2. Hop distance** (`hops_to_first_hard_fact`). Every click between the entry
page and the confirming fact is an exit opportunity. Target: the fact is on the
landing page, or one click away and linked in primary navigation.

**3. Orientation.** The first screen must state, in real text a machine and a
skimming human both read: what this is, who it is for, and one distinguishing
fact. A generic hero headline ("Welcome", "Innovation, delivered") gives a
mid-journey visitor nothing to latch onto.

## Answer-shaped content

Retrieval works on **passages**, not pages. The most quotable unit you can write
is a question-shaped heading followed immediately by a self-contained
one-sentence answer:

```html
<h2 id="battery-life">How long does the battery last?</h2>
<p>The Model 7 runs for 18 hours of continuous playback on a single charge.</p>
```

"Self-contained" is the part people skip. The sentence must survive being lifted
out of its page — name the subject instead of writing "it" or "this". A passage
that needs its neighbours to make sense will be summarised rather than quoted,
and summaries lose attribution.

## Context retention, honestly scoped

The site cannot see the assistant's conversation. So "personalisation" here
means the narrower, achievable thing: **use the context that does arrive.**

| Signal | Available? | What to do with it | Cost |
|---|---|---|---|
| `#anchor` in the URL | Yes | Scroll to it and visually highlight the section | trivial |
| Referrer host | Yes | Detect assistant referrals; segment analytics | trivial |
| UTM parameters | Yes | Carry intent into the page's default state | low |
| Internal search `?q=` | Yes | Keep it in the URL — linkable, measurable | low |
| Returning visitor's own path | Yes, first-party | Surface recently viewed items | medium |
| The assistant's conversation | **No** | Nothing. Do not promise this | — |

Keep recommendations honest about which column they are in. A same-page
highlight for an inbound anchor is a few lines. Genuine server-side
personalisation is a project, and saying so is what makes the rest credible.

## Site search is the safety net

One input box rescues the visitor whose question the navigation does not answer.
Two requirements: put the query in the URL (`/search?q=term`) so it is linkable
and measurable, and log the queries. Those logs are the highest-signal content
backlog available — every search is a question your content failed to answer
where the visitor expected it — and they cost nothing to collect.

## What this probe cannot see, and must not claim

Static analysis reads HTML. It cannot execute JavaScript, so it cannot prove an
overlay blocks first paint, cannot measure real load performance, and cannot
observe actual bounce behaviour. An element with `class="cookie-modal"` may
never render.

Report those as **medium confidence**, state that static analysis cannot
confirm, and name the manual check. Anchor ids, hop counts and text presence are
measured — those are high confidence. Keeping that line clean is what makes the
whole report trustworthy.
