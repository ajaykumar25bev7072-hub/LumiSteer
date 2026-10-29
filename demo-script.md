# LumiSteer — 2-minute demo script

Recording checklist: browser at the frontend URL, backend running
(`uvicorn app.main:app --port 8000`), a key optional (without one the agent
replays the labelled demo cache).

## 0. Setup shot (10 s)
- Landing page: one-sentence pitch and the animated path diagram.
- Say: "A person walking past a VLC link destroys it — LumiSteer's agent
  watches the physics, re-steers a reflecting surface, and explains why."

## 1. Baseline degradation (20 s)
- Launch simulator. Show Stable status: received power ~5.4 µW, BER "< 1e-18".
- Drag the green receiver across the desk — metrics update immediately.

## 2. Blockage event (20 s)
- Click **Block the direct path** (person lands on the LED→receiver line).
- Status flips to Outage; received power collapses; the side view shows the
  blocker covering the beam height.
- Optional: slide ambient light to *high* — an extra way to degrade the link
  without any blocker.

## 3. Agent diagnosis and re-steering (45 s)
- Click **▶ Run agent**. The Agent Console streams:
  1. observation JSON (telemetry), 2. reasoning note ("LOS gain collapsed …
     blockage, not noise"), 3. tool calls (`simulate`, then `robust_optimize`
     over a 15 cm radius), 4. tool results with real numbers, 5. final
     explanation quoting only tool-returned values.
- Point at the recovered metrics: status Stable, BER improved, received power
  up. Emphasize: every number quoted was produced by the physics engine
  through its tools — the LLM is a supervisor, not a calculator.
- Also click the manual **Optimize IRS (point)** / **Robust IRS (15 cm)**
  buttons once to show the app works with no LLM at all.

## 4. Comparison charts (20 s)
- Comparison page → run "Blockage event" scenario.
- Four BER heatmaps side by side (no IRS / random / fixed-point / robust) with
  a colorblind-safe scale; outage-probability bar chart; export CSV / report.

## 5. Blockage timeline (20 s)
- Run the scripted walk: BER vs time for the four strategies, re-steering
  events marked in cyan, classical blockage-risk predictor in gold.

## 6. Methodology (5 s)
- Every equation, default parameter, assumption and limitation — including
  exactly how the Nemotron agent is used (tool selection only) and how it
  never computes metrics.
