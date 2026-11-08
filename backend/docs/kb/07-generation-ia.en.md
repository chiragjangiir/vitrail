---
title: AI content generation
section: content
roles: [CMS_ORG_ADMIN, CMS_DESIGNER, CMS_CAMPAIGN_MANAGER]
keywords: [generation, AI, image, video, music, voice-over, prompt, negative prompt, assistant, image to video, i2v, fal, ElevenLabs, studio, campaign, AI key, BYOK, génération, IA]
---

# AI content generation

Vitrail can generate **images**, **videos**, **music** and **voice-overs**
from a natural-language description. The generated media becomes a normal media in the
media library (per-screen renditions, playlists, audio baskets).

## Prerequisite: your AI keys (BYOK)

Generation uses **your organization's keys** (you pay your own provider).
Configure them in **Settings → AI Keys**:

- **fal.ai**: images, videos, music, voices.
- **ElevenLabs**: music and voices (alternative, commercial quality).
- **Anthropic**: required for the **prompt writing assistant** and the Studio's creative
  director.

Without the relevant key, the feature remains visible but inactive ("configure your AI keys").

## Where to generate

- **Media → Generate (AI)**: a single asset (image, video or audio).
- **Studio**: a complete **campaign** from a brief (visual concepts adapted per
  format, + video / voice / music).

## Writing a good prompt

Generation models are **trained mostly in English**. Enter your prompt
in English if possible, or let the **prompt writing assistant** do it for you.

### The prompt writing assistant

Below the description field, expand **"Prompt writing assistant"**. Describe your
idea in **any language**; the assistant produces an **optimized English prompt** suited
to the chosen model, and a **negative prompt** when the model supports it. The result pre-fills
the fields — it remains **fully editable**. Two modes:

- **Direct**: one idea → one prompt.
- **Conversational**: the assistant may ask 1 to 3 questions before delivering the prompt.

### Good practices

- Describe a **subject + an action + a style**; for video, add the **camera** and the
  **lighting**.
- Keep it **simple**: 3 to 5 elements at most, concrete words.
- Avoid precise numbers ("10 products") and complicated movements.
- Do not write **meta-instructions** ("promotional content to be broadcast on screens"):
  the model does not execute them, it **draws** them — hence unwanted text banners.

### Negative prompt

The **negative prompt** lists what the model must avoid. Useful default values:
`text, banner, watermark, letters, blurry, warped faces`. In particular, it neutralizes embedded text
banners. The field only appears for models that support it (FLUX dev, Qwen,
MiniMax, WAN, Kling…).

## Animate an image (image → video)

To turn an image into a video ("image→video" models), provide a sharp **reference
image**, with a clear subject and no cluttered background. In the prompt, **describe only the
motion** to bring in — not a new scene:

- subtle ambient motion: water, clouds, foliage, steam, light shimmer;
- at most **one** slight camera movement (e.g. *slow push-in*);
- ban "promotional / screens / text / banner / poster" from the prompt, and add them to the
  negative prompt.

## Cost

A **cost estimate** is displayed live (depending on the model, resolution and duration).
To test a style, start with a **short** video (a few seconds) before generating
longer. The Studio displays the campaign's **total cost** before launching generation.
