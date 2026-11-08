---
title: Brand kits — declare once, pre-fill everywhere
section: promo
roles: []
keywords: [brand kit, brand guidelines, brand, colors, palette, accent, ink, background, badge, font, typography, logo, legal notices, tone, visual identity, advertiser, organization, chain, promo generator, promo visual, pre-fill, template, prompt assistant, atmosphere, charte, charte de marque]
---

# Brand kits — declare once, pre-fill everywhere

A **brand kit** gathers what you used to retype for every visual: the colors, the
font, the brand name, its logo, its legal notices and its tone. It is declared
**only once**, and the **Promo Generator** then uses it to pre-fill each
visual.

It is managed from the **Promo Generator** page, **"Brand kits and fonts"** button in the
top bar. Editing it is reserved to the **organization administrator**:
the brand kit decides the visual identity, like custom fonts.

## Two scopes, and which one wins

| Scope | Who it serves |
|---|---|
| **Organization** | the chain itself — its own visuals |
| **Advertiser** | a supplier brand that advertises with you |

There is **at most one brand kit of each**: one for the organization, one per advertiser. When
a visual is made *for an advertiser*, it is **its** brand kit that applies; otherwise the
organization's. A Brightwell visual does not carry the store's colors.

The choice is made in the **"Applied brand kit"** card, at the top of the left column:
*Chain visual*, or the targeted advertiser. The line below always says which brand kit
actually applies — or that there is none.

## A brand kit only replaces what it declares

This is the most important point, and it explains the checkbox in front of each color.

An **undeclared** color is not "white": it means *"the brand kit says
nothing"*, and the template then keeps its own. You can therefore impose only your accent
color and leave the rest of the template intact. Without these checkboxes, setting a single brand
color would silently erase the other four and produce an inconsistent visual.

The same goes for the font: if you declare none, the template's font is
kept.

## It pre-fills, it does not lock

The order is always the same:

**template colors → then the brand kit → then what you enter on this visual.**

So you stay in control: on a given visual, a style setting you set
yourself wins over the brand kit. The brand kit saves you from retyping everything, it does not
lock you in.

**Legal notices** follow the same logic, with one nuance: they are copied
into the *Notices* field **only once**. If you deliberately erase them, they do not
come back.

## The logo and brand name are never drawn by the AI

When you ask for an **AI-generated background**, the brand kit passes **the palette and
the tone** to the model, as an *atmosphere to aim for*. It never asks it to draw your logo,
to write the brand name or the legal notices.

This is intentional: a generative model cannot reproduce a logo faithfully, and it
would write approximate text. These three elements are **placed afterwards**, by compositing,
which is deterministic — therefore exact. The **"Place the brand logo"** button adds the
logo as a layer, which you can then move and resize.

In other words: the AI provides the ambience, compositing provides the accuracy.

## What changes when no brand kit exists

Nothing. As long as no brand kit is created, visuals keep exactly the colors and
font of their template, and the prompt-writing assistant behaves as before.

## Frequently asked questions

**I just changed the brand kit colors, do I need to redo the visuals already
generated?**
Yes. A generated visual is an image: it freezes the colors of the moment. The brand kit acts on
the visuals you generate **afterwards**.

**I chose a font in the brand kit but the visual does not show it.**
Check that it is still present in the organization's **custom fonts**.
If it has been deleted since, the visual deliberately falls back on the
template's font rather than failing.

**Can an advertiser manage their own brand kit from the portal?**
No. An advertiser's brand kit is set from the CMS, by an administrator of
the organization.
