# steer

A live vector-steering console for prose. Text streams in on the left; every
line carries a weight; the knobs on the right write steer vectors from the text
you already have; and a measurement loop tells you, sentence by sentence,
whether the steer actually landed.

It is a control surface **and** an audit, and the audit is the interesting half.

```
pip install -e ".[dev]"
steer                     # zero keys, zero downloads
```

Open http://127.0.0.1:7860 and press **space**.

![the console](docs/shot.png)

---

## Three backends, one console

| provider | what the knobs do | needs |
|---|---|---|
| `mock` (default) | pick continuations from a hand-written literary corpus, biased by the active poles | nothing |
| `api` | compile the vectors into a directive and send it to any OpenAI-compatible endpoint | `STEER_API_KEY`, `STEER_API_BASE`, `STEER_API_MODEL` |
| `mlx` | compute a real contrastive direction in the hidden states and add it to the residual stream at every token | Apple silicon, `pip install -e ".[mlx]"` |

```bash
steer --provider mock --seed keeper
steer --provider api  --model gpt-4o-mini
steer --provider mlx  --model mlx-community/Qwen2.5-3B-Instruct-4bit --layer 0.55 --scale 0.10
```

The console tells you which one is running (`meta.activation`), and the status
bar ends with `mock · corpus`, `api · gpt-4o-mini`, or `mlx · Qwen2.5-3B…`.
Nothing pretends to be the other.

---

## What a steer vector is

A vector is a **pair of poles** plus a signed magnitude:

```
tone      tender  ↔  somber      magnitude +0.62   → pull toward tender
tension   tense   ↔  calm        magnitude -0.40   → pull toward calm
focus     Elara   ↔  narrator    magnitude  0.00   → inert
```

The console **generates these from the document you already have** — it reads
which side of each axis the current text leans to, puts that pole first, and
sets the opening magnitude from the size of the lean. Rewrite the poles in the
dock (or add your own) and they stop being suggestions.

Under `mlx`, each vector also carries a real direction:

```
delta = unit( h(ctx + "voice turns tender") - h(ctx + "voice turns harsh") )
x_l  += scale * magnitude * delta
```

`scale` is expressed in units of the layer's own activation norm, so the same
number behaves consistently across model sizes and layers. Default `0.10`
(≈10% of a 187-unit residual stream on Qwen2.5-3B layer 19). Generation is
chunked and the version counter is re-read between chunks: **moving a knob
mid-stream re-steers the next tokens without restarting the passage.**

### Does it actually move the model? Measure it

Two probes, because "the paragraph looked different" is not evidence:

```
.venv/bin/python scripts/probe_steering.py logits   # is the offset in the graph?
.venv/bin/python scripts/probe_steering.py text     # does greedy output change?
```

Measured on `mlx-community/Qwen2.5-3B-Instruct-4bit`, layer 19:

- offset L2 norm **15.0** against a mean activation norm of **187.2**
- max |Δlogit| **6.20**, mean **0.78** on the next-token distribution
- at temperature 0, `tender` and `harsh` diverge from the first generated
  sentence at gains 0.04 / 0.08 / 0.16, and collapse into meta-text at 0.28 —
  so the working band is roughly **0.04–0.16**, and the dial's top end is a
  real cliff rather than a decoration.


Under `api`, the same numbers are compiled into a directive in the prompt.
That is honest prompting with a control surface on top — and the console says
so, because `activation` is `false` and the note reads `prompt-compiled`.

---

## What the numbers mean

- **rail numbers** (left) — per-line relevance of that line to the live window,
  `0..1`, drawn as block glyphs plus the value. Not attention weights, and the
  code never calls them that; they are a cheap lexical relevance the auditor
  can compute in a millisecond.
- **badges** (right) — for each active vector, the share of evidence its pole
  currently holds: `tone: tender 64%`. Laplace-smoothed so one stray word
  cannot read as a 100% steer.
- **radial dial** — `tension`, `surprise`, `pace`, `mode`, drawn from the last
  900 characters and the text inside your attention boxes.
- **status bar** — words/tokens, live rate, per-token latency, and counters
  `box n`, `steer n`, `pin n`.

`sentences` and `realized` come back in the audit payload, so a client can
assert "detected N sentences, M vectors realized" rather than trusting the
picture.

### Why lexical, and what it costs

The auditor is words, not a second model. That buys three things: it runs on
every tick (~1 ms), it never blocks generation, and it cannot invent a score for
a pole it has never seen — unknown poles fall back to spelling/morphology
matching and split evenly (50/50) when the text is silent.

The cost is real: it measures *register*, not meaning. "The blade came up" is
tense by its words and would score as tense even if the scene is comic. Treat
the readout as a fast instrument, not a critic. `mlx` users get the model's own
hidden states for steering, but the *readout* is still this lexical loop.

---

## Attention boxes

Select text → the selection becomes a box with a weight. Boxes are attended to
by the continuation in proportion to their weight: under `api`/`mock` their
text is injected into the directive and the corpus bias; under `mlx` their
tokens are up-weighted in the anchor. Drag the weight, and the next sentence
leans differently. `box n` in the status bar counts them.

## Keys

| key | action |
|---|---|
| `space` | generate / continue |
| `tab` | open the steer dock |
| `c` | camera (optional, off by default) |
| `r` | reset the passage |
| `esc` | close the dock |

Select prose with the mouse, then use the dock to pin a box on it.

---

## API

`GET /api/state` returns the console state. `WS /ws` streams:

```jsonc
{"cmd":"generate","tokens":160}
{"cmd":"stop"}
{"cmd":"vector","action":"set","id":"v1","magnitude":-0.5}
{"cmd":"vector","action":"add","label":"weather","plus":"storm","minus":"calm"}
{"cmd":"box","action":"add","text":"the faded ink blot","start":10,"end":28,"weight":0.9}
{"cmd":"pin","id":"v2"}
{"cmd":"reset","seed":"keeper"}
```

Server → client: `init`, `state`, `delta`, `audit`, `status`, `error`.

Every `audit` frame is a complete measurement:

```jsonc
{"metrics":{"tension":{"value":0.81,"label":"very strained"}, ...},
 "vectors":[{"label":"tone","pole":"tender","realized":0.64,"magnitude":0.62}],
 "segments":[{"start":412,"end":489,"score":0.71}],
 "words":252,"sentences":11,"realized":2,"rate":58.2,"latency_ms":16.4}
```

---

## Install

```bash
git clone <repo> && cd steer
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q
```

`.[mlx]` for the local-weights path. The `mock` provider needs nothing but
FastAPI, and that is deliberate: the console must be fully alive on a fresh
clone with no keys and no downloads.

## Layout

```
steer/
  lexicon.py      axes, poles, buckets — the vocabulary the audit speaks
  auditor.py      clause tiling, windows, per-vector evidence, per-tick report
  steerer.py      anchor text, directive compiler, activation direction
  state.py        Console / SteerVector / AttentionBox
  server.py       FastAPI + WebSocket, generation loop, steer commands
  providers/      mock · api · mlx (same Protocol, capability-flagged)
  web/            no build step: index.html, console.css, console.js
tests/            behaviour tests (a steer must move the prose)
```

No frontend build, no bundler, no node. The client is one hand-written
`console.js` that talks to the socket and draws the overlay.

## License

MIT. Copyright (c) 2026 Harish Kotra.
