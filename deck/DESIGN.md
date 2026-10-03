---
name: Health Briefing - stakeholder deck
canvas: { width: 1920, height: 1080, fps: 30 }
colors:
  bg: "#F4F7F6"          # off-white, tinted toward teal (never pure white)
  surface: "#FDFEFE"     # cards, report page
  line: "#D3DDE3"        # hairlines and card borders
  ink: "#13294B"         # deep navy: all primary text
  ink-2: "#3B4F6B"       # secondary text (subheads, footers); 7.6:1 on bg
  muted: "#8A97A8"       # decorative only, never body text
  teal: "#0E7470"        # clinical accent: structure, "trusted source", roadmap
  teal-tint: "#DDEFEC"
  ai-blue: "#1F5BC6"     # the AI's actions (slide 2 colour code)
  ai-blue-tint: "#E1EAFA"
  amber: "#A85A00"       # your team's actions (text/stroke)
  amber-fill: "#F2A93B"  # amber shapes (checks, cursor)
  amber-tint: "#FCEBCF"
  coral: "#B83A33"       # conflict (text/stroke)
  coral-tint: "#FBE2DF"
  green: "#16773D"       # resolved / ready
  green-tint: "#DDF2E4"
typography:
  family: "Atkinson Hyperlegible Next"   # OFL 1.1, shipped in assets/fonts, one family only
  weights: { display: 800, emphasis: 700, label: 600, body: 400 }
  sizes: { headline: 58, bubble: 44, card: 40, body: 40, kicker: 40, stamp: 76, minimum: 40 }
  tracking: { display: "-0.02em", body: "-0.005em" }
spacing: { gutter: 80, gap: 24, card-padding: "18px 24px", radius-card: 20, radius-pill: 999 }
motion:
  eases: [ "expo.out (headlines)", "power3.out (cards)", "power2.inOut (camera, morphs)", "back.out(1.4) (pops, badges)", "sine.inOut (ambient drift)" ]
  durations: { fast: 0.3, medium: 0.6, slow: 1.0, ambient: "whole scene" }
  rules: [ "no flashing", "no infinite loops", "one paused GSAP timeline per scene", "fromTo only" ]
---

# Health Briefing - design spec

## Overview

A calm, clinical, trustworthy look for **non-technical health-system strategy leaders**.
The visual story is a single analyst's week (a Monday question for a Friday meeting; with Health Briefing the briefing is ready before Friday), told with a
small set of objects that carry over between slides: the question bubble, six source cards,
the calendar chip, the option chips and the decision note.

The deck uses only its own neutral palette and fonts; no external brand assets.

## Colour code (the one rule viewers must learn)

| Meaning | Colour | Where |
|---|---|---|
| Trusted sources / structure | Teal `#0E7470` | source icons, roadmap, report labels |
| **The AI** | Blue `#1F5BC6` | step 2, AI reading zone, quote icons, the AI's flag |
| **Your team** | Amber `#A85A00` / `#F2A93B` | step 3, cursor, checks, decision note |
| Conflict | Coral `#B83A33` | "Sources disagree", clashing card edges |
| Resolved / ready | Green `#16773D` | step 4, "Friday · Briefing ready" |

Slide 2 shows a small key ("Blue = AI · Amber = your team") once; slides 1 and 3 keep the
same meanings without repeating it.

## Typography

- One OFL family: **Atkinson Hyperlegible Next** (Braille Institute), chosen because it was
  designed for maximum legibility, which suits a healthcare audience and a projector at the
  back of a boardroom. Weight contrast does the hierarchy work: 800 headlines, 600 labels,
  400 body.
- **Minimum text size is 40px** at 1080p for anything the audience reads. Headlines 58px,
  question bubble 44px, closing stamp words 76px.
- No exceptions: on slide 3 the report condenses by animating its real width and height (not
  `scale`), and its end state is three 44px proof lines, so nothing on the final hold is smaller
  than 40px.
- Long text uses `text-wrap: balance` so no line ends with a stranded word.
- Sentence case everywhere; no all-caps labels.

## The frame

- 1920x1080, 80px outer gutter, light canvas.
- Background layer on every scene: tinted off-white, a faint teal dot grid that drifts slowly,
  and one soft radial glow. Decoratives never carry content.
- Cards: `#FDFEFE` surface, 3px `#D3DDE3` border, 20px radius, one soft navy-tinted shadow.
- Icons: Lucide (ISC), inlined as SVG paths, 2.25px stroke at 36-48px.

## Motion

- Calm and executive: staggered reveals, cards flying in and converging, SVG line draws,
  check-mark draws, a timeline drawing left to right with markers popping in, gentle
  camera push/pull on slide 2. No bounces beyond `back.out(1.4)`, no flashing, no shake.
- Each scene follows build / breathe / resolve; first motion starts 0.1-0.3s in.
- Slides 1 and 2 end with a 0.45s exit (fade and a 16px lift) so the MP4 never hard-cuts. The
  question bubble stays through the slide 1 exit because it is the match-cut into slide 2.
- Final states keep the message at full strength: on slide 1 only the supporting cast dims,
  on slide 2 the team's decision stays on screen, on slide 3 the proof lines are full size.
- Ambient motion differs per scene (slide 1 diagonal grid drift, slide 2 glow breathing,
  slide 3 slow ring rotation) and is always attached to the scene's paused timeline.

## Do / don't

- Do label every example as an example ("Illustrative scenario", "Example condition", "Example").
- Do keep both guideline cards fully readable whenever they are on screen; the deck never
  endorses one clinical target.
- Don't show invented numbers. The only figures are the real ADA / ACP targets (with their
  sources: ADA Standards of Care 2025, ACP guidance statement 2018), the product's real trust
  tiers (1 guideline, 2 systematic review, 3 National Library of Medicine summary, 4 other), the
  decision-log count (one entry per option chosen or set aside plus one per settled conflict, as
  the product logs them) and "2-3 conditions" in the ask; "minutes, not weeks" is always
  labelled "Goal".
- Don't use jargon (no "LLM", "RAG", "API", "embeddings").
