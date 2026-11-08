---
title: Promo Generator — making a promotional visual
section: promo
roles: []
keywords: [promo generator, promo, promo visual, promo poster, price, strikethrough price, was price, discount, promotion, slogan, legal notices, product, background, backdrop, background removal, cut-out, layout, template, format, resolution, layer, layers, preset, product URL, extract, compliance, readability, generate, promo video, animation, series, series mode, several visuals, bulk, batch, CSV, CSV import, spreadsheet, Excel, paste, table, row, several products, générateur promo, prix barré]
---

# Promo Generator — making a promotional visual

The **Promo Generator** produces a promotional poster (image or short video) from
a product, a price and a layout. The result goes into the **media library** and is
played like any other media item.

**Where**: Media → **Promo Generator**.

🔑 **What the machine makes and what it never invents.** The price, the strikethrough price, the
discount, the product name and the **legal notices** are placed by compositing from
what you entered — they are **never** requested from an AI model. The AI is only used for the
**background** (and for cutting out the product). This is what guarantees that a displayed price is the price
you typed.

## The flow, in six steps

The left column is a **flow**. Only one step is open at a time: opening the
next one closes the previous one, so that all the fields of a step fit on screen. A
**collapsed step shows its value**, so you can read the full state of the visual in six lines.
They open in any order, as many times as you want.

| # | Step | What you do there |
|---|---|---|
| 1 | **For whom?** | My chain, or an advertiser. **The brand kit follows from it** — colors, font, logo, notices. |
| 2 | **The product** | Paste the URL of a product page (automatic extraction), pick an image from the media library, or import one. Background removal available. |
| 3 | **Text and price** | Slogan, price, strikethrough price, discount, currency, legal notices, media name. |
| 4 | **Layout** | The template, the format (16:9 or 9:16) and the resolution. |
| 5 | **The background** | An image from the media library, or an AI-generated background (ambience + description). |
| 6 | **Free edits** | Add text or image layers, movable on the preview. |

## Starting from a product URL

In step 2, paste the address of a product page and click **Extract**: the name, the price and the
photo are retrieved and pre-fill the form. **Everything remains editable** — extraction
is an input aid, not a source of truth. You remain responsible for the data
displayed and for the rights to the image.

## The price is mandatory

A promo visual without a price makes no sense: the **Generate** button stays disabled while it
is missing, and the banner under the preview **says what is missing and takes you to the relevant step**.

The same banner flags **readability** problems (text too long for its
slot, insufficient contrast). These checks are re-applied by the server at
generation time: you cannot produce an unreadable visual by bypassing the screen.

## Choosing an image

The **Product** and **Background** steps open the **media library drawer**: folder tree,
search, preview. The search runs **server-side**, so it also finds images that
are not on the first page. The **Import** button next to it uploads a file from
your computer.

💡 An advertiser's visuals are automatically filed under **Advertisers / &lt;name&gt;**.

## AI-generated background, and background removal

- **Generate the background** (step 5): choose an *ambience*, optionally an *area to leave
  empty* (so the product or the price can sit there) and a free description.
- **Cut out** (step 2): removes the background of the product photo and returns a transparent PNG.

Both use your **organization AI key** (BYOK) and are therefore subject to any spending
caps. A quota refusal is announced **before** the call, with the figures.

## Image or video

Under the preview, **Image** or **Video**. For video, set the duration (3 to 15 s) and the animation
(zoom in, zoom out, static). The video is encoded by the server: it appears in
**Visuals produced**, on the right, when it is ready.

## Series mode — one template, N products

The **"Single visual / Series"** toggle, at the top of the page, replaces the preview with a **table**:
one row per visual.

🔑 **Sharing is the heart of this mode**: the left-hand flow keeps defining what is
**common** (brand, layout, background, notices, currency, edits); the table only carries what
**varies** — product image, slogan, price, strikethrough price, discount. This sharing is what turns
twelve visuals from twelve complete flows into twelve rows.

**Three ways to fill the table**, which can be combined:

- **Add a row** and type directly — to correct or complete.
- **Import a CSV** — the file only needs the columns that vary. Headers are
  recognized in French as well as English (`nom`/`produit`/`slogan`, `prix`, `prix barré`, `remise`),
  in any order, with or without accents.
- **Paste from a spreadsheet** — copy the cells in Excel or Google Sheets and paste them:
  tab-separated columns are recognized just like the `;` of an Excel export.

⚠️ **Without a recognized header, the columns are read IN ORDER** (name, price, strikethrough price, discount)
and the screen says so. Check the table: it is the only case where a price could end up
in the wrong column.

ℹ️ Importing **adds** to the table, it does not replace it: you can import two files, or
complete an import by hand.

### An incomplete row does not stop the series

A row **without a price** is highlighted, marked "missing price", **named** in the warning
under the table — and **skipped**. The rest of the series goes ahead anyway. The button shows how many
visuals will actually be produced: "Generate the 4".

Each visual is **named after its product**: otherwise, N visuals would arrive in the
media library under the same name. Their progress is shown in **Visuals produced**, on the right.

## Chaining several visuals

- **Redo with another product** (after a generation) keeps the brand, the layout, the
  background and the notices, and only clears the product and its price.
- **Presets** (top left) saves the complete configuration to recall it
  later.

## Frequently asked questions

**The Generate button is grey.** Read the banner under the preview: it names what is missing (most
often the price) and offers to go to the relevant step.

**My colors are not the brand's.** Step 1: check who the visual is made for.
Without a brand kit, the visual keeps the template's colors. See the *Brand kits* article.

**I cannot find my image.** Use the drawer's search rather than scrolling: it
queries the server and covers the whole media library, not just the first page.

**Where did my visual go?** In the media library, under the name given in step 3 (or a default
name). The **Visuals produced** panel keeps the list for the current session.
