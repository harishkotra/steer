# Credits

## The original work

**steer** exists because of **[Spaceship IDE](https://github.com/chuanqisun/spaceship)** by
**[Chuanqi Sun](https://chuanqisun.com)** — MIT Media Lab.

Spaceship IDE is the original "steer your ideas in realtime, space pilot style" demo. Its four
conjectures are the conceptual spine of this project, and this console would not exist without it:

1. **Focus monitor** — visualize what the model is paying attention to, and use that to guide the
   reader's focus.
2. **Attention lock** — force the model to attend to specific phrases, biasing what it writes next.
3. **Future vector steering** — decompose the task into eigenvectors, tune each independently, and
   re-compose them to influence the incoming text.
4. **Realtime re-generation** — explore alternative futures by scrubbing, when generation is cheap.

If you build on this work, cite the original:

```bibtex
@misc{sun2026spaceship,
  author       = {Sun, Chuanqi},
  title        = {Spaceship {IDE}: Steer Your Ideas in Realtime, Space Pilot Style},
  year         = {2026},
  publisher    = {GitHub},
  howpublished = {\url{https://github.com/chuanqisun/spaceship}},
  note         = {Demo: \url{https://chuanqisun.github.io/spaceship/}}
}
```

- Original repo: <https://github.com/chuanqisun/spaceship>
- Live simulator: <https://chuanqisun.github.io/spaceship/>
- Licence: MIT

## What is his, what is new here

This is an independent implementation, not a fork — no code was copied. The ideas in the left column
are his; the work in the right column is what this repository adds.

| from Spaceship IDE | what steer adds |
|---|---|
| the console metaphor: dials beside a live text stream | a Python + MLX backend, so "steering" can mean a hidden-state intervention rather than only a prompt |
| attention lock as an interaction | a **measured** box: `×N` lift computed over the text written after the box, or `no pull yet` |
| vector steering as a conjecture | axes **mined from the passage** with the justifying sentence attached, at every 220 characters |
| focus monitor | a forward **relevance** rail — deliberately not called attention weights, because it is a lexical score |
| exploring alternatives by scrubbing | a **blind test**: two futures, one steered, the reader guesses, the auditor rules |
| — | **per-sentence verification**: which dial each new sentence realised, with the share that earned the claim, and `unclaimed` when none did |

## Everything else

- Built by [Harish Kotra](https://harishkotra.me) — more builds at [dailybuild.xyz](https://dailybuild.xyz).
- Model weights: [Qwen2.5-3B-Instruct-4bit](https://huggingface.co/mlx-community/Qwen2.5-3B-Instruct-4bit) (Apache-2.0) via [MLX](https://github.com/ml-explore/mlx) / [mlx-lm](https://github.com/ml-explore/mlx-lm) (MIT).
- Server: [FastAPI](https://fastapi.tiangolo.com) + [uvicorn](https://www.uvicorn.org) (MIT/BSD).
- The lighthouse passage, the corpus in `providers/mock.py`, and all prose in this repo were written for this project.
