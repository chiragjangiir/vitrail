---
title: Server page and encoding duration
section: exploitation
roles: []
keywords: [server, encoding, transcoding, ffmpeg, GPU, hardware acceleration, NVENC, VAAPI, slow, long, queue, decision required, awaiting_decision, estimate, calibration, bands, 20 minutes, 4 hours, lower resolution, 1080p, 720p, downscale, progress bar, throughput, work disk, media worker, storage, capacity, serveur, encodage]
---

# Server page and encoding duration

Every imported video is **re-encoded** so that every screen in the fleet can play it.
It is by far the heaviest task the server performs: depending on the machine and the source, it
takes a few seconds or several hours. The **Server** page (`/settings/server`) helps you
understand *why*, and the estimation mechanism helps you not find out too late.

## What the Server page shows

**Encoding capacity.** The line that explains almost everything: *hardware acceleration
active* or *no hardware acceleration*. Without a usable graphics card, encodings
run on the processor and are **much slower** — a factor of 5 to 10 on a 4K video.
The page also shows the encoders selected for H.264 and HEVC, and the number of cores.

**Observed throughput.** The speeds actually measured during previous encodings, per
encoder. It is an observation, not a promise: it comes from your own files.

**Work disk.** The free space where the worker writes its temporary files. A
full disk makes encodings fail without the cause being obvious anywhere else.

**Encoding queue.** What is in progress, waiting, or waiting for a decision.

> **"No media worker is responding."** This message is not a display detail: it
> means that no encoding can complete. The information on this page comes from the
> **worker** and not from the web server — it is the worker that has ffmpeg and sees the hardware. When
> it does not respond, the page **says so** rather than showing stale values.

## Who sees this page

The **licence holder**: the platform super-admin, or the administrator of an
organization on a server that has no super-admin. On an integrator's server, a
brand administrator does not have access and therefore does not see another
client's queue. If your server is administered by a service provider, the screen tells you so: the
capacity and the queue are part of their operations, your content is processed normally.

## The three duration bands

Before starting an encoding, the server **measures**: it encodes about ten seconds of
**your** file with the exact command that will be used, then extrapolates. A test
pattern would encode much faster than a real shot — we would promise 15 minutes and take
40.

| Estimated duration | What happens |
|---|---|
| **under 20 minutes** | the encoding starts on its own |
| **between 20 minutes and 4 hours** | **you decide**: the media waits, marked *Decision required* |
| **over 4 hours** | refused by default; an administrator can override |

**A refusal is not a dead end.** The screen offers to encode at a **lower resolution**
(1080p, 720p), each with its own estimate: a 4-hour 4K often becomes a
25-minute 1080p. The media remains visible and filterable in the media library until the
decision is made.

> **If measurement is impossible, nothing is blocked.** The server never refuses an
> encoding based on an estimate it could not make — a check that cannot conclude
> does not decide.

## The progress bar

During encoding, the media drawer shows the actual progress and an estimate of the time
remaining, then a **finalization** phase (upload to storage, conformance check)
— without it, a bar stuck at 99 % would read as a crash. If the worker dies, the
bar **disappears** instead of staying frozen: that is the right failure mode, it tells you that
nobody is working anymore.

## Frequently asked questions

**"My encoding has been running for hours."** Open the Server page: if hardware
acceleration is missing, that is the most likely explanation. Compare the elapsed time with
the estimate shown at launch.

**"I imported a video and nothing happens."** Look at the media library: the media may
be in *Decision required*. It is waiting for your call, it is not broken.

**"Why is my 4K so slow?"** Beyond Full HD, the product encodes in HEVC,
heavier than H.264. On a server without a graphics card, it is the most costly case
there is — hence the duration bands.

**"The announced speed does not match."** The estimate comes from a sample of your
own file: a source whose complexity varies a lot (static shots then motion)
deviates more. The decision band exists for that.
