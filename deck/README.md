# Health Briefing: stakeholder deck (HyperFrames)

A three-slide animated presentation of the **Health Briefing** prototype for non-technical
health-system strategy leaders (VP Strategy, service-line directors, planning analysts).
It is built with the open-source [HeyGen HyperFrames](https://github.com/heygen-com/hyperframes)
framework (Apache-2.0), pinned to `hyperframes@0.8.114`.

The story follows one analyst's week. On Monday a planning question arrives for Friday's meeting,
and doing it by hand eats the week (slide 1). The AI reads the sources and the team makes the
calls (slide 2). With Health Briefing the calendar rewinds to Monday: the briefing is ready
before Friday, followed by the roadmap and the ask (slide 3).

| Slide | Headline | Length | Hero visual |
|---|---|---|---|
| 1 | Today, one planning question can take days or weeks of source-hunting. | 0-19s | Source cards circle the question; two guidelines clash; "Scattered · Slow · Hard to trace" |
| 2 | The AI does the reading; your team makes every call. | 19-39s | Blue (AI) hands over to amber (your team); the decision log counts every choice; a real, sourced guideline disagreement is settled by a person and logged |
| 3 | Every briefing arrives sourced, dated and traceable. | 39-60s | The report builds itself, then condenses into three proof lines beside the roadmap and the ask |

## Two outputs from the same three scenes

A HyperFrames *slideshow* cannot be rendered to one linear MP4, so the project has two entry points.
Both mount the **same** scene files in `compositions/`.

| Output | Entry | Used for |
|---|---|---|
| Slideshow deck | `index.html`: master timeline plus the `application/hyperframes-slideshow+json` island (one slide per scene, fragments at the beat boundaries, narration and Q&A in the presenter notes) | `npx hyperframes present`, live with a presenter view |
| Linear video, 60s | `video/index.html`: the same three scenes back to back. `npm run video:sync` (`scripts/sync-video.mjs`) copies `compositions/` and `assets/` into `video/` first; `lint`, `check` and `render` run it for you. The copies are git-ignored; never edit them | `npx hyperframes render`, giving an MP4 to email or loop |

> **Present mode is click-to-build, with no motion.** The HyperFrames slideshow controller
> *seeks* to each fragment's hold point and does not play the timeline between them, so each
> click jumps straight to the next fully built state and the audience never sees the animation.
> **If the motion matters in the room, present from the MP4 instead:** play
> `dist/health-briefing-stakeholders.mp4` in a video player and pause at these click times:
>
> | Slide | Pause at (mm:ss.s) |
> |---|---|
> | 1 | 0:03.5 · 0:08.9 · 0:14.0 · 0:18.4 |
> | 2 | 0:22.5 · 0:28.0 · 0:32.9 · 0:38.4 |
> | 3 | 0:43.5 · 0:49.6 · 0:52.5 · 1:00 (end) |
>
> Use present mode when you need the presenter view (notes, Q&A) more than the motion.
> `npm run preview` scrubs the timeline in Studio.

## Commands

Needs Node 22 or later and FFmpeg. Run everything from this folder.

```bash
npm ci                         # installs the pinned hyperframes@0.8.114 CLI (dev dependency)
export HYPERFRAMES_NO_TELEMETRY=1 HYPERFRAMES_NO_UPDATE_CHECK=1

# Browser: hyperframes needs a Chrome headless shell. Either let it fetch one ...
npx hyperframes browser ensure
# ... or point it at an existing one. Example path only (for example the one
# Playwright installs); replace it with the headless shell on your machine:
export HYPERFRAMES_BROWSER_PATH=/path/to/chrome-headless-shell
npx hyperframes doctor

npm run present     # slideshow + presenter view on http://localhost:3004 (press P for the audience tab)
npm run preview     # HyperFrames Studio: scrub and edit the timeline (deck entry)
npm run video:sync  # copy compositions/ and assets/ into video/ (lint, check and render do this first)
npm run lint        # static lint: deck and video
npm run check       # lint, runtime, layout, motion and WCAG contrast, all with --strict, sampled at
                    # every presenter hold point (--at) and every tween boundary (--at-transitions)
npm run snapshot    # PNG stills (mid-animation and final state per slide) into dist/snapshots/
npm run render      # 60s MP4 -> dist/health-briefing-stakeholders.mp4 (1920x1080, 30fps)
```

Presenting over a video call: click **Present** (or press **P**) to open the audience tab. In
Google Meet, share that *tab*. In Zoom, drag the audience tab into its own window and share the
window. Each slide's notes (narration, likely question, answer) appear only in the presenter view.
`SPEAKER_NOTES.md` has the same material for rehearsal.

`present` works offline. The HyperFrames runtime and GSAP are vendored in `assets/vendor/`, so
the deck fetches nothing from a CDN. The only 404s you will see are the optional navigation
sound effects (`sfx/*.mp3`), which this deck leaves out on purpose.

## Layout

```
index.html               slideshow deck (master root + JSON island)
video/index.html         linear video entry (same scenes; compositions/ and assets/ copied in by video:sync)
scripts/sync-video.mjs   copies the deck's compositions/ and assets/ into video/
compositions/
  s1-problem.html        slide 1 - one paused GSAP timeline, 19s
  s2-how.html            slide 2 - one paused GSAP timeline, 20s
  s3-briefing.html       slide 3 - one paused GSAP timeline, 21s
assets/fonts/            Atkinson Hyperlegible Next (variable) + OFL.txt
assets/vendor/           gsap 3.14.2, HyperFrames runtime 0.8.114
assets/licenses/         licence notices (see below)
DESIGN.md                palette, type, motion rules (HyperFrames design-spec format)
SPEAKER_NOTES.md         per-slide script, timing, Q&A, transitions
dist/                    build output (git-ignored): MP4 + snapshots
```

Rules the scenes follow (from the official `hyperframes-core` and `hyperframes-animation` skills):
- One paused timeline per scene, registered on `window.__timelines["<scene id>"]`.
- `fromTo` tweens only, with `immediateRender: false` on every later tween of the same target.
- No `Date.now`, `Math.random`, network access or CSS transitions.
- Every font is local and declared with `@font-face`.
- All readable text is at least 40px at 1080p.

## Content guardrails

- Every example is labelled: "Illustrative scenario", "Example condition", "Example". The
  blood-sugar disagreement is real and sourced on screen. The American Diabetes Association
  (Standards of Care in Diabetes, 2025, section 6) says below 7% A1C for many nonpregnant adults;
  the American College of Physicians (guidance statement, 2018) says 7% to 8% for most people
  with type 2 diabetes. Both cards stay readable, and the check mark lands on "Your team's call",
  not on either guideline.
- Claims match the product contract (`../docs/CONTRACT.md` §7.2-7.3): trust tiers are
  1 guideline, 2 systematic review, 3 National Library of Medicine summary, 4 other; the AI
  pre-selects its suggestions and proposes a rule-based default for each conflict, and a person
  confirms or changes every one; unmatched quotes are kept with a warning; the decision log gets
  one entry per option chosen or set aside and one per settled conflict.
- There are no invented statistics. "Minutes, not weeks" is always labelled **Goal**. "2-3
  conditions" is the ask.
- Safety framing appears on screen on slides 2 and 3: public research only, no patient data,
  decision support rather than medical advice.
- The deck uses only its own neutral palette and fonts; no external brand assets.

## Licences

| Asset | Licence |
|---|---|
| HyperFrames CLI (dev dependency) and the vendored runtime `hyperframe.runtime-0.8.114.iife.js` | Apache-2.0 (HeyGen), full text in `assets/licenses/HYPERFRAMES-LICENSE.txt` |
| Atkinson Hyperlegible Next font | SIL Open Font License 1.1 (`assets/fonts/OFL.txt`) |
| Lucide icon paths, inlined as SVG | ISC (`assets/licenses/LUCIDE-LICENSE.txt`) |
| GSAP 3.14.2 | GSAP Standard "no charge" license (`assets/licenses/GSAP-NOTICE.txt`) |

See `assets/licenses/README.md` for sources and versions.
