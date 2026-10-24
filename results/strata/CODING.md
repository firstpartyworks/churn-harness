# Browser-game coding test: Qwen3.8-Flash-Next vs Qwen3.8-27B, thinking on (2026-10-23)

Same box as `RESULTS.md`. Flash-Next: UD-IQ4_XS on Strata 0.2.2 (V100 + P40 helper). 27B: Q6_K on stock llama.cpp,
V100 alone. Per-run numbers: `coding-runs.csv`. Harness: `coding/` (`coding_bench.py`, `fix_bench.py`, `shoot.js`).

## Protocol

- Two tasks, one HTML file each, no libraries: a Breakout-style brick breaker (paddle on mouse + arrows, angle by hit
  position, 5+ brick rows, score, 3 lives, start / game-over / win screens, R restarts) and a small tower-defense game
  (winding path, waves that get harder, click to place towers that cost gold, gold for kills, lives, next-wave button,
  game-over screen). "Reply with only the HTML file in one code block."
- Thinking on, Qwen's thinking sampler (temperature 0.6, top_p 0.95, top_k 20), seeds 1, 2, 3, one user turn.
  Both chat templates default to reasoning effort "xhigh", which adds "think carefully through the task, validate key
  assumptions, consider plausible alternatives" to the prompt; "low" adds "keep your thinking brief and focused".
- Every page opened headless (JavaScript errors, screenshot at load and after start input). Played by hand (phone):
  Flash-Next Prism Breaker, BrickBreak, NeonBreaker, Emberfall Road; 27B Shatter, Grid Defense, both 64K Brickstorms.
  The rest are headless-only, marked below. Every reported bug was traced to its line.

## Results at default effort

| | Flash-Next (Strata) | 27B (llama.cpp) |
|---|---|---|
| finished under a 30,000-token cap | 0 / 6 (all cut off mid-code) | 2 / 6 |
| finished with 62,000 tokens | 6 / 6 (29k-48k tokens) | 4 / 4 reruns (34k-59k tokens) |
| minutes per game | 6.6-10.9 | 18.8-44.1 |
| generation speed | 71-75 tok/s | 22-24 tok/s |
| thinking share of output | 43-76% | 68-77% |
| first-try games (best run per seed) | 4 work (2 hand, 2 headless), 2 broken | 3 work (2 hand, 1 headless), 1 works but power-ups can't be caught, 1 broken, 1 not yet checked (Emberpath: headless test never got past its intro button) |

Bugs, each one line or one structure:
- Flash-Next "NeonBreaker": `b.r` where it meant `balls[i].r` in the ball loop; the game loop throws every frame, so
  the title screen never gives way to play.
- Flash-Next "Emberfall Road": a second, empty `function update()` stub ("separate from update() game step") below the
  real one; JavaScript keeps the later definition, so the simulation never runs and queued enemies never spawn.
- 27B "Brickstorm" (s1): the click handler is on the canvas, but the start-screen overlay covers it and takes the
  click; Space works, click and tap do nothing (unplayable on a phone).
- 27B "Brickstorm" (s3): the power-up catch test requires the 20 px capsule to lie inside the 14 px paddle, which never
  happens; every capsule falls through.

Flash-Next's six games are all different (six names, each with its own short story text and extras nobody asked for:
sound, power-ups, levels, upgrade/sell, speed controls). The 27B's 30K-run games work and are plainer; its 64K reruns
are more elaborate; two of its three Breakouts are named "BRICKSTORM".

## Fix turn

The original task, the model's own reply (thinking dropped, as chat apps do), then a symptom-only report in a player's
words ("pressing space or clicking on the start screen doesn't start the game"; "Send Wave bumps the wave counter but
no enemies ever show up"; "clicking on the start screen does nothing"; "power-ups go right through the paddle").
Three tries each.

| bug | fixed | how checked |
|---|---|---|
| Flash-Next, NeonBreaker (doesn't start) | 0 / 3 | 2 still throw `b is not defined`, 1 has a new syntax error |
| Flash-Next, Emberfall Road (no enemies) | 3 / 3 | enemies on the road 30 s after Send Wave (original: none) |
| 27B, Brickstorm click to start | 3 / 3 | start overlay hidden after a click on the canvas (original: stays) |
| 27B, Brickstorm power-ups | 3 / 3 | catch test rewritten as a proper overlap test (code read, not played) |

On NeonBreaker the report described a symptom ("doesn't start") that points at input handling; all three Flash-Next
tries rewrote input handling, one wrapped the render loop so "a stray error can never freeze it", and none looked at
the ball loop. The browser's own error message names the line. Fix turns took Flash-Next 4.2-7.1 min, the 27B 9.0-9.5.

## Flash-Next at lower effort (64K, same seeds)

| effort | finished | tokens | minutes | thinking share | headless: loads without error |
|---|---|---|---|---|---|
| default (xhigh) | 6 / 6 | 29k-48k | 6.6-10.9 | 43-61% | 5 / 6 |
| medium | 6 / 6 | 3.3k-5.9k | 0.6-1.2 | 3-26% | 6 / 6 |
| low | 6 / 6 | 3.8k-6.6k | 0.7-1.3 | 6-23% | 6 / 6 |
| thinking off | 6 / 6 | 10.7k-18.3k | 2.2-4.0 | 0% | 5 / 6 (one syntax error) |

The effort instruction shapes the code, not just the thinking: at medium and low the games are short and plain
(9-15 KB of HTML); with thinking off the games are as elaborate as at xhigh (30-48 KB, named, styled), in a third
of the time. Medium and low were checked headless only.

## Standing server at 64K context

Strata 0.2.2 helper, `--max-context 65536` vs 32768 (same speed protocol as `RESULTS.md`): story 65.8 vs 68.6,
code 84.5 vs 90.7, 8K-doc 73.7 vs 69.5 tok/s, prompt read 932 vs 968 tok/s. Within run-to-run spread; the expert
cache still hit 98.9% during the 64K coding runs.

## Played by hand (phone), second pass

| set | Breakout | Tower defense |
|---|---|---|
| Flash-Next medium | 3 / 3 paddle moves only on tap (mouse-move only; no touch handling) | 3 / 3 work, plainer; #1 shows tower range |
| Flash-Next low | 3 / 3 same paddle issue | #1 works; #2 enemies can't be killed; #3 works, shows range |
| Flash-Next thinking off | #3 same paddle issue (listens for pointer moves but lets the page scroll instead) | #1 and #3 no visible map; #2 map hard to read |
| Flash-Next fix turn | NeonBreaker 0 / 3 | Emberfall 3 / 3 (and it ships a tower-upgrade system) |
| 27B fix turn | Brickstorm click 3 / 3, power-ups 3 / 3 (and a red danger gradient as the ball nears the floor) | - |

The paddle issue is touch input: the prompt asked for mouse and arrow keys, and the medium/low games handle exactly
that (likely fine on a desktop, not tested there). Every default-effort (xhigh) Flash-Next Breakout added touch
support unasked. Verdict after playing: xhigh Flash-Next for polish; thinking-off Flash-Next lands near the 27B at
xhigh in quality, at a fraction of the time (2-4 min vs 19-44 min).

## Rerun at the Qwen model-card sampling (2026-10-23 evening)

Both Qwen3.8 model cards: thinking mode temperature 1.0, top_p 0.95, top_k 20, min_p 0, presence penalty 0;
non-thinking 0.7 / 0.8 / 20, presence penalty 1.5. Same tasks, seeds 1-3, 60,000-token limit, 64K context
(`coding_bench.py --preset card`). Checked with `coding/playtest.js` (desktop + phone touch, video per run;
calibrated against the hand play-through: 7 of 8 games matched) plus a look at each final frame. Not yet hand-played.

| arm | finished | minutes | tokens | likely work | broken | unclear |
|---|---|---|---|---|---|---|
| Flash-Next xhigh | 6 / 6 | 7.5-9.3 | 32k-40k | 4 | 2 (syntax errors) | 0 |
| Flash-Next medium | 6 / 6 | 0.7-1.2 | 3.3k-5.6k | Breakouts mouse-only again; TDs run | 0 errors | - |
| Flash-Next low | 6 / 6 | 0.7-2.0 | 3.3k-8.9k | Breakouts mouse-only again; TDs run | 0 errors | - |
| Flash-Next thinking off | 6 / 6 | 1.7-4.1 | 8.1k-18.2k | 2 | 3 | 1 |
| 27B xhigh | 4 / 6 (2 hit 60k) | 26.8-45.2 | 37k-60k | 3 | 0 | 1 |
| 27B thinking off | 6 / 6 | 6.1-8.3 | 8.4k-11.2k | 4 | 1 | 1 |

Against the earlier 0.6 sampler: Flash-Next xhigh broken games went from logic slips to syntax errors (2 of 6 both
times); the 27B at xhigh overthought further (2 of 6 never finished within 60k). Thinking off did worse at the card's
non-thinking settings: several errors are mismatched identifiers (`last is not defined`, `ball_R is not defined`),
which fits presence penalty 1.5 pushing the model off tokens it already used, and code reuses its names.
Hypothesis only: not tested by toggling the penalty alone.

### Card-sampling rerun, played by hand (desktop, 2026-10-24)

| game | verdict |
|---|---|
| Flash-Next xhigh Breakout 1 "Prism Breaker" | works, very laggy |
| Flash-Next xhigh Breakout 2 "Blockfall" | works, smooth, polished (expanding rings at ball contacts) |
| Flash-Next xhigh Breakout 3 "Brick Breaker" | broken: ball never launches, stays stuck to the paddle |
| Flash-Next xhigh TD 1 "Irongrove" | works, polished, good animations |
| Flash-Next xhigh TD 2 "Emberward", TD 3 "Emberline" | broken: no map, nothing to place (syntax errors) |
| Flash-Next thinking-off Breakout 1 "NeonBreaker" | broken: bricks fill the play area, ball won't launch |
| Flash-Next thinking-off Breakout 2 "NeonBreaker" | works, ball very slow, sounds play slightly early |
| Flash-Next thinking-off Breakout 3 "BrickWorks" | broken: sound only, empty play area |
| Flash-Next medium Breakouts 1-3 | all work (desktop), plain, no sound, nearly identical |
| Flash-Next medium TDs 1-3 | all work, plain, no sound (#3 naval-themed) |
| Flash-Next low Breakouts 1, 3 | work; Breakout 2 mostly works (ball always launches from the centre) |
| 27B xhigh Breakout 1 | works, looks good, a bit slow, bricks crack before breaking |
| 27B xhigh Breakout 2 | works, laggy, same crack effect, less polished |
| 27B xhigh TD 1 "Thornkeep" | works, looks good (the monsters have eyes) |
| 27B xhigh TD 2 "Thornbrae" | broken: opens on the failed screen |
| 27B thinking-off Breakout 1 "Bricksmith" | broken: can't start a game |
| 27B thinking-off Breakout 2 "Breaker" | works, ball very slow, no sound |
| 27B thinking-off Breakout 3 "NeonBreaker" | broken: freezes on start |
| 27B thinking-off TD 1 "Bastion" | broken: enemies cross the whole map in an instant, towers can't track them |
| 27B thinking-off TD 2 "Bulwark" | works perfectly, nice look |
| 27B thinking-off TD 3 "Bulwark" | broken: same as TD 1 |

Bastion and TD 3 share one bug: the path length is counted in grid cells while enemy speed is in pixels per
second, so enemies move one cell per pixel - 48x too fast in Bastion (48-px cells), 64x in TD 3 (64-px cells).
The code otherwise runs; the automated tester saw lives lost but could not tell that from towers being outgunned.

Not yet played: Flash-Next thinking-off TDs, low TDs. So far at xhigh: Flash-Next 3 of 6 work (2 polished
standouts: Blockfall, Irongrove), 27B 3 of 6 (2 never finished, 1 broken) - same rate, Flash-Next 3-5x faster.
