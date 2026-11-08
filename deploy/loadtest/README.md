# Load test — reconnection burst

🇫🇷 [Version française](README.fr.md)

Tooling for the "400 screens reconnect at the same time" measurement. It used to live in `/tmp`
and disappeared at the first reboot: it is kept here so it never has to be rewritten.

## What is measured

400 player WebSocket connections opened **simultaneously**, and the delay until the first
`player:sync`. This is the delay a screen experiences when a site gets power back or a server
restarts.

## Protocol

1. **Create the test data set on the machine under test** — `mk_players.py N` (in the backend
   container, `PYTHONPATH=/app`) creates N `LOADTEST-*` players and prints their tokens.
   The tokens are forged **on the spot** and **stored in the database**: the WebSocket compares the
   presented token with the stored token, so a token that is merely signed would be rejected.
2. **The generator runs on ANOTHER machine**, in a disposable container:

   ```
   printf 'FROM python:3.12-slim\nRUN pip install --no-cache-dir websockets\n' \
     | docker build -t sfloadgen -
   SF_URL=ws://<cible>:8080/api/v1/ws/player bash burst.sh <label> <procs> 400
   ```

   `<cible>` = the target machine. `procs` = 1 (one process × 400) or 2 (two processes × 200).
3. `agg.py` aggregates the outputs and reports p50 / p95 / max over the **union** of latencies.

## Pitfalls — each one has produced a wrong number at least once

- **The generator's `ulimit -n`.** The production backend container is at **1024**: running the
  generator inside it makes the instrument hit its own limit. Hence the disposable container with
  `--ulimit nofile=65536`.
- **The first run after a backend restart must be discarded.** Measured: +6 % with 1 worker but
  **+46 % with 4 workers** — each process pays for its own startup. Including cold runs therefore
  biases the A/B **systematically against** multi-worker: this is what once led to the wrong
  conclusion that `--workers` only gained ×1.8.
  Corollary: a `docker compose up -d` **recreates nothing** if the configuration has not changed —
  check `StartedAt`, otherwise you think you are measuring cold when you are measuring warm.
- **`loadavg` does NOT measure a burst.** It is a one-minute sliding average; over a 10 s burst it
  massively underestimates (0.37 recorded where actual utilization was 100 %). Measure the deltas
  of `/proc/stat`, and `docker stats` for the container.
- **A probe needs a freshness witness.** An expired sampler leaves a log full of old values that
  `tail` serves without complaint: compare the last timestamp with `date +%s` and **refuse** to
  conclude beyond 5 s.
- **The generator itself.** Verified: splitting the generator (2×200) changes nothing (≤ 4 % at 1,
  4 and 8 workers) — but this must be re-checked as soon as a configuration drops well below one
  second.
- The **interleaving** witness of `agg.py` is mandatory in 2-process mode: two generators taking
  turns instead of overlapping would produce half the load and a wrong verdict.

## After the test

Delete the players: `delete from cms_players where player_name like 'LOADTEST-%'`.
On a non-disposable machine (e.g. a canary server), stack the test configuration in a **separate**
compose file (`-f docker-compose.yml -f docker-compose.override.yml -f lt.yml`): the original
override carries the NVIDIA acceleration, it must never be replaced.
