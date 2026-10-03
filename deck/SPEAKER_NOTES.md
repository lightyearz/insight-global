# Health Briefing: speaker notes

**Audience:** health-system strategy leaders (VP Strategy, service-line directors, planning analysts).
**Format:** 3 slides. The animated video runs about 60 seconds; live, with questions, allow about 4-5 minutes.
**Live deck:** `npm run present`. Each slide builds in four clicks (fragments); the notes below are also in the presenter view. Present mode jumps to each built state and shows **no motion**.
**Video:** `dist/health-briefing-stakeholders.mp4` (60s, silent; read the narration over it, or let it loop before the session).
**If the motion matters in the room, present from the MP4:** play it and pause at the click times listed under each slide (they match the present-mode clicks). Use present mode only when you need the presenter view more than the animation.

Plain-language rule: say "AI", "trusted sources" and "you stay in control". Avoid "LLM", "RAG", "API" and "embeddings".

---

## Slide 1: Today, one planning question can take days or weeks of source-hunting.

**On screen**
- Calendar chip at top right: "Monday", with "Planning meeting · Friday" underneath.
- Tag: "Illustrative scenario".
- A question bubble with an "Example condition" tag: "What's the standard of care for type 2 diabetes today?"
- Six source cards: Clinical guideline, Systematic review, National Library of Medicine, Journal article, Guideline update, Professional society.
- Three closing words: Scattered · Slow · Hard to trace. No figures. At the end the cards and calendar dim; the headline, the three words (now teal) and the question stay at full strength.

**Time:** 0:00-0:19 in the video, about 60-75 seconds live.

**Click builds (presenter), with MP4 pause times:**
1. 0:03.5. The question is typed out.
2. 0:08.9. The sources circle the question and the headline appears.
3. 0:14.0. Two guideline sources drift together and clash, and the calendar flips to Thursday.
4. 0:18.4. Three words stamp in; the supporting cards dim.

**Narration**
> Picture one of your analysts on a Monday. Friday is the diabetes service-line planning meeting, and the question is simple: what's the standard of care today? The answers are out there, in clinical guidelines, research reviews and National Library of Medicine resources. But they're scattered, updated at different times, and sometimes they disagree. Pulling all of that into one briefing can take days or weeks, and it's hard to trace where each point came from. That's the gap Health Briefing closes.

**Likely question:** "Our analysts already do this well. What's actually broken?"
**Answer:** Their judgment isn't the problem. The slow part is finding, reading and organizing the sources, and keeping track of which one is newest. The AI takes on that part, so analysts can spend their time on the decisions that need their expertise.

**Transition:** The question is the only thing still lit. "So what happens when the analyst hands this question to Health Briefing?" On slide 2 the bubble shrinks into the search box.

---

## Slide 2: The AI does the reading; your team makes every call.

**On screen**
- Colour key: Blue = AI · Amber = your team.
- Four steps: 1 Type a condition, 2 AI reads & suggests, with quotes (blue), 3 You choose & settle conflicts (amber), 4 Briefing ready (green).
- Suggested options with quote icons, tagged "Example": Lifestyle changes, Metformin, GLP-1 medicines. Weight-loss surgery is shown as "Set aside for this briefing".
- "Blood-sugar target (A1C)". "Real example: two published guidelines disagree."
  - American Diabetes Association: below 7% for many adults.
  - American College of Physicians: 7% to 8% for most adults.
- Each source tile carries its trust tier (1 clinical guideline, 2 systematic review, 3 National Library of Medicine summary, 4 everything else), the same rule the product uses.
- "Decision log" chip at top right: it counts 1, 2, 3 as your team ticks the options, 4 when weight-loss surgery is set aside, and 5 when the conflict is settled (the product logs each option chosen or set aside and each settled conflict).
- Each guideline card names its source: "Standards of Care, 2025" (ADA) and "Guidance statement, 2018" (ACP).
- "Sources disagree", with a blue flag from the AI; it turns amber and reads "Settled by your team".
- "Your team's call · Logged" stays on screen; an amber dot carries it into the decision log.
- Footer: "Public research only · No patient data · Decision support, not medical advice".

**Time:** 0:19-0:39 in the video, about 75-90 seconds live.

**Click builds (presenter), with MP4 pause times:**
1. 0:22.5. "Type 2 diabetes" is typed into the search box.
2. 0:28.0. Sources stream in with their trust tiers; options appear; your team checks three and sets one aside (log: 4).
3. 0:32.9. The two guidelines meet, the AI flags the clash, and a person makes the call.
4. 0:38.4. The decision is logged (log: 5), step 4 turns green and the safety footer appears.

**Narration**
> Here's how it works. The analyst types a condition. The AI, shown in blue, reads trusted public sources and suggests treatment options, each with a quote from its source. The small number on each source is its trust tier: clinical guidelines are tier 1. Then your team, shown in amber, takes over. The AI pre-selects its suggestions, and your team confirms or changes every one: here, three options in and one set aside for this briefing, and each choice is logged. When sources disagree, like these two published guidelines with different blood-sugar targets, the AI flags the conflict, shows both sides with quotes and dates, and suggests a default using a simple, visible rule. A person makes the final call, and it's logged.

**Likely question:** "What if the AI gets something wrong, or makes something up?"
**Answer:** The AI pre-selects its suggestions; your analyst confirms or changes every one before the report is written, and any quote it couldn't match word-for-word to the source is flagged with a warning, never silently dropped. Sources are graded by a fixed rule: tier 1 is a clinical guideline, tier 2 a systematic review, tier 3 a National Library of Medicine health summary, tier 4 everything else. An option's confidence is capped when its quote can't be found in the source.

**Delivery notes**
- Point at the two guideline cards and say plainly that this is a real, well-known disagreement (ADA Standards of Care 2025; ACP guidance statement 2018) and that the deck takes no side. The check mark lands on "Your team's call", not on either target.
- If asked "does the AI pick one?": it suggests a default with a simple rule (the more authoritative source type wins, then the newer date), shows that rule, and a person makes the final call.
- Say "logged", not "explained": the log records who decided and when, and a note is optional.

**Transition:** "Now, the same question with Health Briefing." Slide 3 opens with the calendar rewinding from Thursday to Monday: "Ready before Friday".

---

## Slide 3: Every briefing arrives sourced, dated and traceable.

**On screen**
- Calendar chip: "Monday · Ready before Friday" (green). The calendar rewinds from slide 1's Thursday.
- Report page "Type 2 diabetes · Standard of care", tagged "Example", with five sections:
  - Summary
  - Timeline
  - Treatment options (the three chosen options, each with a source link)
  - Decision log ("A1C target · your team's call")
  - Sources (Clinical guideline · Tier 1, Systematic review · Tier 2, Library of Medicine summary · Tier 3), each tied by a line to the option it supports
- The report then condenses into three proof lines: "Every option linked to its source", "Every decision logged", "Every source dated and trust-rated".
- Roadmap: Now: Standard of care, tagged "Working prototype" · Next: Emerging treatments · Then: Key companies & institutions.
- "Goal: a sourced first draft in minutes, not weeks."
- "The ask: pick 2–3 conditions your team cares about. Let's pilot together."
- Footer (same as slide 2): "Public research only · No patient data · Decision support, not medical advice".

**Time:** 0:39-1:00 in the video, about 75-90 seconds live, then questions.

**Click builds (presenter), with MP4 pause times:**
1. 0:43.5. The report starts building: summary and timeline.
2. 0:49.6. Options, decision log and sources appear, with lines tying each option to its source.
3. 0:52.5. The report condenses into three proof lines and the roadmap rises.
4. 1:00 (end). The goal, the ask and the safety footer appear; hold here for discussion.

**Narration**
> With Health Briefing, the same question has a briefing ready well before Friday. It has a one-paragraph summary, a timeline, the treatment options your team chose and a record of every decision. Every option is linked to its source, and every source is listed with when it was published, when it was researched, and its trust tier. Standard of care works today as a prototype. Emerging treatments come next, then the key companies and institutions. Our goal is a sourced first draft in minutes, not weeks. The ask: pick two or three conditions you care about, and let's pilot together.

**Likely question:** "What would a pilot need from us, and is our data safe?"
**Answer:** We'd need two or three priority conditions and an analyst to review and confirm the options. We'd compare each draft with how your team builds that briefing today, and you decide whether it holds up. It reads public medical literature only and never touches patient data. It's for strategy and planning, not patient care. It runs on Google Cloud using Google's Gemini AI models.

**Delivery notes**
- "Minutes, not weeks" is a **goal**. Say "goal" every time.
- Only the standard-of-care section exists today, as a working prototype. Emerging treatments and key players are future work.

**Close:** Stay on the ask. "Which two or three conditions would you want to see first?"

---

## Quick Q&A cheat sheet

| If they ask... | Say... |
|---|---|
| Is this medical advice? | No. It supports strategy and planning decisions, not patient care. |
| Does it use our patient data? | No. It uses public medical literature only and never touches patient data. |
| Who decides what goes in? | Your team. The AI pre-selects options with quotes and suggests a default for each conflict; a person confirms or changes every one, and each decision is logged. |
| Does the AI pick a winner when guidelines disagree? | It suggests a default using a simple, visible rule (more authoritative source type first, then the newer date). A person makes the final call. |
| What if a quote is wrong? | Any quote the AI couldn't match word-for-word to its source is kept but flagged with a warning, and that option's confidence is lowered. |
| How do we know a source is current? | Every source shows when it was published and when it was researched, plus a trust tier. |
| What's built today? | The standard-of-care section, as a working prototype. Emerging treatments come next, then key companies and institutions. |
| How fast is it? | Our goal is a sourced first draft in minutes rather than weeks. A pilot is how we'd measure that against your current process. |
| Where does it run? | Google Cloud, using Google's Gemini AI models. |
