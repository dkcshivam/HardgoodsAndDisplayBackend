# Architecture

Derived from [DesignBrief.md](DesignBrief.md), the working prototype
(`Packing App.dc.html`) and the 23 mockup screens (`Packing App Mockups.dc.html`)
in the Claude Design project.

This is the reference document. When code and this file disagree, one of them is
a bug — decide which, then fix it.

---

## 1. Purpose

DKC manufactures furniture and store display goods in India and exports them to
retailers in the US and UK. Before a container ships, every carton leaving the
building must be recorded: number, contents, weight, dimensions, volume.

Three parties consume that record, and each punishes an error differently:

| Consumer | Cost of a wrong record |
|---|---|
| Customs | Shipment held at port; duty recalculated |
| Shipping line | Billed against wrong volume or weight |
| Merchant | Cannot locate goods on arrival |

Today this is produced by hand in spreadsheets.

**The app has one job:** turn an order into a verified carton plan.

```
   "3 tables, 6 chairs, 4 mirrors"   ──▶   13 numbered cartons
   (what the merchant asked for)            (what physically ships)
                                            + proof they match
```

The verification is the point. A spreadsheet will let you pack five chairs
against an order for six. This app refuses to save until the counts agree.

### Non-goals

This is not a sales, inventory, or ERP system. There is no price field, no stock
level, no invoicing. Every attribute in the catalogue answers one question:
*how does this go in a box?*

---

## 2. Scope

**In scope now:** the Hardgoods module — furniture and homeware — and the
Display module — store decor and small goods. Display differs structurally
enough to be its own Django app with its own tables, sharing only the
arithmetic in `apps/common`. Fully described in §10.

**Not yet designed:** authentication and roles, photo editing beyond upload and
set-main, photos for display products.

---

## 3. Glossary

The vocabulary is the spec. Ambiguity here becomes bugs downstream.

### Entities

| Term | Definition |
|---|---|
| **Product** | A packing recipe for one SKU, identified by Style No. Not a sale item — it has no price or stock. Written once, reused by every future order. |
| **Item** | Casual synonym for Product. Deliberately **not** a table. |
| **Part** | One separately-boxed component of a multi-part product ("Table top", "Legs set"). Carries the same depth of data as a whole single-box product. |
| **Carton** | One physical shipping box, belonging to exactly one order. Its dimensions are entered directly. |
| **Carton Content** | What is inside a carton: a product, optionally a specific part, and a quantity. Separate from Carton because one carton may hold several different things. |
| **Order** | A merchant's purchase to fulfil. Header plus lines. |
| **Order Line** | One row of the order: `{product, quantity}`. Commercial only — says nothing about boxes. |
| **Merchant** | The customer shipped to (Urban Outfitters, West Elm). |
| **Category** | A product label (Table, Chair, Storage). Set **once per product**, never per part. A list column, never a grouping. |

### Measurements

| Term | Definition |
|---|---|
| **Product weight** | The bare item, no packaging. Entered. |
| **Box weight** | The empty carton alone. Entered. |
| **Packing material weight** | Padding and filler inside the box, excluding the box. Entered. |
| **Net weight** | Everything inside the box. **Derived.** |
| **Gross weight** | The whole sealed carton, as a courier would weigh it. **Derived.** |
| **CBM** | Volume of the shipping box in cubic metres. **Derived.** |
| **Pack per box** | Units of a single-box product per carton. Drives carton splitting. |
| **Assembled dimensions / weight** | Size and weight of the finished multi-part item. **Reference only** — never used in any calculation, because the item never ships assembled. |

### Documentation

| Term | Definition |
|---|---|
| **Style No** | Unique SKU identifier (`DKC-TBL-OAK-01`). Enforced unique at database level. |
| **Description** | Internal / trade name. |
| **Customs description** | Formal name for shipping documents; frequently differs from Description. |
| **HSN code** | Harmonized System Nomenclature code determining duty classification. Held at **part** level for multi-part products, since parts of different materials classify differently. |

### Process

| Term | Definition |
|---|---|
| **Auto-pack** | Generates a proposed carton set from the ordered products' recipes. A starting point, fully editable afterwards. |
| **Reconciliation** | Ordered quantity vs actually packed quantity, per product. |
| **Blocker** | A validation failure that prevents saving the packing plan. |

---

## 4. Units and formulas

Decided once. Never mixed. Every column carries its unit in the name so a
mismatch is visible at the point of use.

| Quantity | Unit | Suffix |
|---|---|---|
| Dimensions | inches | `_in` |
| Weights | kilograms | `_kg` |
| Volume | cubic metres | `cbm` |

```
CBM   = (length_in × width_in × height_in) / 61 023.744094732284

NET   = product_weight_kg + packing_material_weight_kg
GROSS = NET + box_weight_kg
```

Per-carton variants, used by auto-pack, where product weight is per unit but
packing material and box are per carton:

```
CARTON NET   = product_weight_kg × qty + packing_material_weight_kg
CARTON GROSS = CARTON NET + box_weight_kg
```

All monetary-precision arithmetic uses `Decimal` in Python, never `float`.
Weights quantize to 3 decimal places, CBM to 4.

Canonical implementations:
- `apps/common/calc.py` (this repo) — **source of truth**
- `src/lib/calc.ts` (Frontend repo) — mirror, for live form feedback only

---

## 5. Data model

Nine tables in three groups, mirroring `apps/`.

```
   MASTERS                         CATALOG
   ─────────────                   ─────────────
   Category ───────────────────▶ Product ◀───┐
                                  │         │
                                  ├──▶ ProductPart ◀─┐
                                  │         │        │
                                  └────┬────┘        │
                                       ▼             │
                                  ProductImage       │
                                                     │
   ORDERS                                            │
   ─────────────                                     │
   Merchant ──▶ Order ──┬──▶ OrderLine ─────────────▶│
                        │                            │
                        └──▶ Carton ──▶ CartonContent┘
```

### masters

**Category** — `name`(unique) · `is_active`

**Merchant** — `code`(unique) · `name` · `contact_name` · `email` · `phone` ·
`city` · `country` · `is_active`

**Store** — `merchant`→ · `code` · `name` · `contact_name` · `email` · `phone` ·
`ship_{line1,line2,city,state,postal_code,country}` · `is_active`

One outlet of a merchant: the merchant buys, the store receives. `code` is the
merchant's own store number and is unique **within that merchant** only — two
chains may both number a store 118. Used by Display (§10.4.2); a Hardgoods
order still carries a single ship-to address of its own.

### catalog

**Product** — `style_no`(unique) · `style_name` · `description` · `category`→ ·
`customs_description` · `hsn_code` · `is_multi_part` · `status` ·
`assembled_{length,width,height}_in` · `assembled_weight_kg` · `pack_per_box` ·
*plus the PackSpec block*

**ProductPart** — `product`→ · `name` · `description` · `customs_description` ·
`hsn_code` · `{length,width,height}_in` · `sort_order` · *plus the PackSpec block*

**ProductImage** — `product`→ *or* `part`→ (exactly one, enforced by CHECK
constraint) · `image` · `is_main` · `sort_order`

Rows order main-first, so the leading image is the one lists and summaries want.
The first photo an owner receives becomes its main one until another is chosen.

### orders

**Order** — `number`(unique, generated) · `name` · `merchant`→ · `buyer_name` ·
`ship_{country,line1,line2,city,state,postal_code}` · `status`

**OrderLine** — `order`→ · `product`→ · `color` · `quantity` — unique on
`(order, product)`

`color` lives here, not on Product: the same style ships in whatever finish the
merchant asked for this time. The packing list no longer prints it — the
document follows the one the shipping desk sends by hand, which has no colour
column. One colour per product per order — two finishes of one style in a
single order would need colour on `CartonContent` too, and is not supported.

**Carton** — `order`→ · `carton_no` · `{length,width,height}_in` ·
`gross_weight_kg` · `sort_order` — unique on `(order, carton_no)`

**CartonContent** — `carton`→ · `product`→ · `part`→(nullable) · `description` ·
`quantity` · `unit` · `net_weight_kg`

### PackSpec — the shared block

Abstract model in `apps/common/models.py`, inherited by both `Product` and
`ProductPart`. Defining it once makes it impossible for the weight rules to
drift between the single-box and multi-part paths.

```
box_length_in · box_width_in · box_height_in
product_weight_kg · box_weight_kg · packing_material_weight_kg
────────────────────────────────────────────────────────────
net_weight_kg · gross_weight_kg · cbm     (properties, not columns)
```

### The two product shapes

`is_multi_part` selects which half of `Product` is meaningful:

| | Single-box (`false`) | Multi-part (`true`) |
|---|---|---|
| Product PackSpec | populated | **empty** |
| `pack_per_box` | meaningful | ignored (always 1 per part) |
| `assembled_*` | optional | reference information |
| Customs / HSN | on the product | **on each part** |
| Parts | none | 2 or more |

The constraint that a multi-part product has no box of its own is enforced in
`Product.clean()` and in `ProductSerializer.validate()`.

`is_multi_part` is **fixed once the product is saved**. Changing it would silently
re-interpret every carton, weight and reconciliation already recorded against the
style number. `ProductSerializer.validate()` rejects the change, Django Admin
renders the field read-only on an existing row, and the product form replaces the
chooser with the chosen shape. A different shape means a different style number.

---

## 6. Design decisions

### D1 — Derived values are properties, never columns

`net_weight_kg`, `gross_weight_kg` and `cbm` are recomputed on every read.

*Rationale:* a stored derived value can silently desynchronise from its inputs
after any bug, migration or manual edit, and nothing surfaces the error. It then
appears on a customs document. If it is never stored it can never be stale.

*Cost:* a few microseconds per read. Accepted.

### D2 — Carton and CartonContent are separate tables

*Rationale:* a Hardgoods carton needs `part_id` on its contents for D3 to make
reconciliation exact, and that does not flatten onto `Carton`.

*Cost:* one extra table and one join. Accepted.

*Amended:* this decision originally rested a second argument on Display sharing
the table for its mixed-content cartons. Display now has its own tables (§10.1),
so only the D3 rationale above still stands. The decision is unchanged; one of
its two reasons is gone.

### D3 — `part_id` on CartonContent makes reconciliation exact

*Rationale:* the prototype computed `packed = total_quantity ÷ part_count`, which
produces "2.5 of 3 packed" when a carton is removed — not a real quantity, and it
had to be rounded for display, hiding the problem.

Instead each content row records its part, and reconciliation counts each part
separately then takes the **minimum**:

```
   3 table tops boxed, 2 leg sets boxed  →  2 complete tables
```

That is both correct and actionable: *find a leg set.*

### D4 — Inches for dimensions, kilograms for weight

*Rationale:* the prototype's CBM constant (`0.0000163871`) is the inch³→m³
conversion; the mockups labelled fields in cm. The two disagreed by a factor of
~16. Inches match the working prototype and the trade's practice for furniture.

Every column carries its unit in the name so the mistake cannot recur silently.

### D5 — Business rules live only in Django

Auto-pack, blocker detection and status gating exist solely in
`apps/orders/services.py`. The frontend mirrors *calculations* for live feedback
but never *decisions*.

*Rationale:* frontend code runs on the user's machine and can be modified. A
validation rule enforced only there is not a rule.

### D6 — Rules enforced in both code and database

Duplicate carton numbers and duplicate order lines are rejected by application
validation *and* by database `UniqueConstraint`.

*Rationale:* application code gives good error messages; the database guarantees
the invariant regardless of how the row was created. Neither alone is sufficient.

### D7 — snake_case field names in TypeScript

`src/types/index.ts` in the Frontend repo uses `style_no`, not `styleNo`, matching DRF output.

*Rationale:* eliminates a translation layer, which is a class of bug removed
rather than managed.

### D8 — Django Admin is a first-class delivery vehicle

`admin.py` in each app is fully configured — fieldsets, inlines, computed
displays — not left at defaults.

*Rationale:* it provides a complete working CRUD application from day one. Master
data can be maintained there indefinitely, deferring custom screens and
letting effort go to the product form and packing workspace, which Admin cannot
express well.

### D9 — Two repositories (revised)

`HardgoodsAndDisplayBackend` and `HardgoodsAndDisplayFrontend`, each with its own
git history and its own `docker-compose.yml`. This document lives in the backend
repo, which owns the domain model.

*Originally a monorepo*, on the reasoning that the two halves change together —
an API field rename touches both, so one commit, one review, one history.

*Revised* to two repositories for a clearer separation while learning the stack.

*Cost, accepted:* a change to the API contract now spans two repos and two
commits, with nothing enforcing that both happen. The exposure is real:

| Change | Breaks |
|---|---|
| Rename a serializer field | `src/types/index.ts`, every screen reading it |
| Change an endpoint path | `src/lib/queries.ts` |
| Change a validation rule | `src/lib/packing.ts`, which mirrors it |

*Mitigation:* say so in the backend commit message when the contract moves, and
keep §9 of this file accurate — it is the only written record of the contract.

The two halves meet only in the browser: the frontend calls
`http://localhost:8000/api` over the published port, so no shared Docker network
is needed. What binds them is CORS — the backend's `CORS_ALLOWED_ORIGINS` must
list wherever the frontend runs.

---

## 7. Business rules

### Editing a product

`is_multi_part` cannot change after creation (§5). Everything else can, because
the packing recipe is expected to be corrected as the item is weighed and boxed
for real.

Parts are matched to their existing rows by `id` when a product is saved, so
editing a part keeps its photos and keeps any carton content pointing at it.
A part absent from the payload is deleted.

### Photos

A photo belongs to exactly one owner — a product or a part, never both — and can
only be attached once that owner has an id. The product form therefore queues
photos taken against an unsaved product or a newly added part and uploads them
the moment the save returns.

### Auto-pack

For each order line:

**Multi-part product** — for each part, emit one carton per ordered unit.
Quantity 1, box and dimensions from that part, gross from that part's weights.
*3 tables × 2 parts = 6 cartons.*

**Single-box product** — split quantity by `pack_per_box`:
`ceil(qty / pack_per_box)` cartons, each holding `min(pack_per_box, remaining)`.
*6 chairs at 2/box = 3 cartons.*

Carton numbers run sequentially `BOX-001`, `BOX-002`, …

Parts are the outer loop so each part's cartons form one unbroken run —
`BOX-004 – BOX-006` for the tops, `BOX-007 – BOX-009` for the leg sets.
Numbering one whole unit at a time instead would put a part's boxes on every
second number, which the packing list could only print as a rule; a carton
range that has to be decoded is one somebody miscounts at a port. The floor
therefore packs all of one part, then all of the next.

Auto-pack **replaces** the existing plan. It is a proposal; every field remains
editable afterwards, because the box actually used is not always the box planned.

### Reconciliation

Per order line:

- Single-box: `packed` = sum of content quantities for that product with no part
- Multi-part: `packed` = **minimum** across parts of that part's total quantity

`is_matched` when `packed == ordered`.

### Blockers

The packing plan cannot be saved while any of these hold:

| Code | Condition |
|---|---|
| `missing_carton_no` | carton number blank |
| `duplicate_carton_no` | number used more than once in the order |
| `missing_dimensions` | carton length, width or height blank — CBM would be zero |
| `gross_below_net` | carton gross weight < sum of its contents' net weight |
| `quantity_mismatch` | any reconciliation row unmatched |

Save validates inside a transaction and rolls back on any blocker, so a plan with
known problems cannot reach the database whatever the client does.

### Packing list

`GET /orders/{id}/packing-list/` renders the stored plan as an Excel sheet: a
heading block naming the order, merchant, buyer and ship-to address, then one row
per **distinct thing packed** —

```
Carton Nos · Cartons · Style No · Customs Description ·
Qty/Box · Units · NNW (kg) · N.W. (kg) · G.W. (kg) ·
L (cm) · W (cm) · H (cm) · CBM
```

The wording and the order follow the packing list the shipping desk already
sends out by hand, so one desk reads both without learning two conventions.
Display prints the same columns minus `Cartons`.

Twelve identical cartons of one chair are one row, not twelve. The sheet is as
long as the order has different items rather than as long as it has boxes, which
is how a customs officer and a shipping line both read it.

Cartons merge when the box and its single content agree on every printed field —
product, part, description, quantity, unit, net weight, gross weight and all
three dimensions. Reweigh one box and it breaks out onto its own row, which is
the point: a merged row asserts those cartons really are interchangeable. A
carton holding more than one different product never merges.

`Carton Nos` collapses consecutive numbers to `BOX-001 – BOX-003`, and names
each run when a hand-edited plan leaves gaps: `BOX-001 – BOX-003, BOX-007`.
Every number a row covers is either printed or inside a printed run — nothing
is abbreviated into a rule the reader has to decode. Auto-pack numbers each
part's cartons together precisely so this stays a plain range.
**Every figure on a row describes one box**, however many boxes the row stands
for. `Qty/Box` is what a single carton holds, not the run's total, and the three
weights are that carton's.

The three weights are distinct on purpose: `NNW` is the goods alone — unit
weight times how many are in the box; `N.W.` adds the packing material; `G.W.`
adds the carton. `NNW` is worked out from the piece rather than read off
`CartonContent.net_weight_kg`, which folds the padding in on Hardgoods and not
on Display.

Dimensions print in **centimetres to two places**, converted from the inches
the app stores, and `CBM` is worked from those printed centimetres rather than
from the inches behind them — so a broker who multiplies the three numbers on
the page arrives at the fourth. Two places rather than one because an inch is
exactly 2.54 cm: a whole-inch box converts with no rounding at all, and the
sheet's CBM then equals the one the app computed in inches.

The footer is **not** a column sum. A row standing for twelve identical boxes
prints one box's figures, so the totals multiply each row by its run: they are
computed values, not `SUM()` formulas. Dimensions are deliberately not totalled.

`Customs Description` takes the content's own wording, then the piece's
`customs_description`, then its style name — a blank here is a document a
broker cannot clear.

Available as soon as cartons exist — a draft list is what the floor works from
while the order is packed — and built from what is **stored**, so the screen
disables the button while there are unsaved edits.

### Status ladder

```
   draft ──▶ packing ──▶ packed ──▶ shipped
                            ▲
                            └── gated: requires zero blockers
                                and at least one carton
```

Transitions are one-way and one step at a time. Saving a valid packing plan on a
`draft` order advances it to `packing` automatically.

Order numbers are `HG-{year}-{0000}`, sequential within the year.

---

## 8. Screen map

From the 23 mockup screens. Status reflects the custom Next.js frontend; ✅ Admin
means the function is already available through Django Admin.

### Hardgoods

| # | Screen | Status |
|---|---|---|
| 01 | Dashboard — needs-attention panel + recent orders | ✅ Built |
| 02 | Products — list (flat, category as a column) | ✅ Built |
| 03 | Product — first-time setup (Style No, Category, Description, single vs multi-part) | ✅ Built (one form) |
| 04 | Product form — single item | ✅ Built |
| 05 | Product form — multiple parts (collapsible part cards) | ✅ Built |
| 06 | Products — inactive view | ✅ Built (filter) |
| 07 | Categories — list | ✅ Built |
| 08 | Category — add / edit | ✅ Built |
| 09 | Orders — list | ✅ Built |
| 10 | Order — create (details → ship-to → products) | ✅ Built |
| 11 | Packing — draft, blocked | ✅ Built |
| 12 | Packing — reconciled, saved | ✅ Built |

Every Hardgoods screen is built. Photos are part of the product form: a gallery
on the product itself — the item for a single-box product, the assembled item for
a multi-part one — and a second gallery inside each part card, since a packer
needs to see the component, not the finished piece. Both take files from disk or
a photo from the device camera, captured in the app.

The packing screen carries a **Packing list** button that downloads the Excel
document described in §7.

### Display (§10)

| # | Screen | Status |
|---|---|---|
| 13 | Display Products — list | ✅ Built |
| 14 | Display Product — form | ✅ Built |
| 15 | Pack Templates — library list | ✅ Built |
| 16 | Display Orders — list | ✅ Built |
| 17 | Display Order — create (details → stores → per-store demand) | ✅ Built |
| 18 | Display Packing — store overview, then the step loop | ✅ Built |
| 19 | Template editor — authored in-flow against remaining demand | ✅ Built |
| 20 | Stores — list and form, under Admin | ✅ Built |

**The store picker came back.** An earlier revision of this document recorded
that the product × store matrix from the original mockups had been dropped and
a display line was plain `{product, quantity}`. That was wrong about the
business: a display order is one PO for many outlets, and §10.4.2 is the
correction. The mockups' *matrix* is still gone — at fifty stores and thirty
products it is thirteen hundred mostly-empty cells — replaced on screen 17 by:

- a checkbox list choosing which stores are on the order,
- a **bulk fill** (`product` × `qty` → *Fill all N stores*) for the uniform
  case, which is most of them,
- a per-store editor for the exceptions, with a running count of stores still
  empty, since a forgotten store is the easy mistake to make.

Screen 18 opens on the **store overview** — every store with its packed/ordered
count and carton count — because at fifty stores the first question is which
ones are unfinished, not what to pack next. Choosing one narrows to the step
loop below.

That loop lists **steps**, not cartons: each row is a template, its count, what
it consumed and what remained. Remaining demand leads the section, since it is
what the next template gets authored against; a step's carton count opens the
drill-down, which reads the paginated `cartons/` endpoint. Once a store is
packed, the screen offers to copy its plan to every identical unpacked store.

Screen 19 is one dialog (`components/display/template-dialog.tsx`) used from both
the library page and the packing screen. Opened from packing it receives the
order's remaining quantities, pre-fills a row per leftover product, shows how
many units of each are left beside the inputs, and reports how many times the
design would fit — so a template is written against the remainder rather than
from memory. Its `is_library` tick is what keeps one-off tail templates out of
the next order's picker.

### Admin (shared)

| # | Screen | Status |
|---|---|---|
| 20 | Merchants | ✅ Built |
| 23 | Settings | Not built |

### Shared shell patterns

Left nav with three collapsible groups (Hardgoods, Display, Admin) plus a
standalone Dashboard; top bar with derived breadcrumb and search; command palette
on ⌘K / Ctrl+K; confirm dialog; toast stack. The packing screen adds a sticky
footer — a layout sibling of the scroll area, not page content — carrying
blockers, totals and Save.

### Form conventions (standing rules)

From `CLAUDE.md` in the design project:

- Strict vertical flow, one logical group per row
- Dimension groups (L/W/H, or L/W/H + CBM) may share a row
- **Every weight field gets its own row**
- Parts are collapsible cards expanding in place, never a dense table, never a
  separate page per part
- Product photos section sits above the Parts section
- Save lives at the bottom of the form, not in the header

---

## 9. API surface

Base: `/api/`. DRF `PageNumberPagination`, page size 50.
`COERCE_DECIMAL_TO_STRING = False` — decimals serialize as JSON numbers.

| Endpoint | Methods | Notes |
|---|---|---|
| `/categories/` | CRUD | |
| `/merchants/` | CRUD | |
| `/products/` | CRUD | light serializer on list (carries `main_image`), full on detail; parts written in the same request |
| `/product-images/` | POST | multipart: `image` plus `product` **or** `part` |
| `/product-images/{id}/` | PATCH, DELETE | `is_main` promotion; delete removes the file too |
| `/orders/` | CRUD | nested `lines` (each with `color`); `shipping_address` nested on read and write |
| `/orders/{id}/packing/` | GET | full plan: cartons, reconciliation, blockers, totals, `can_save` |
| `/orders/{id}/packing/` | PUT | replace all cartons; 400 + blockers if invalid |
| `/orders/{id}/auto-pack/` | POST | build and apply a proposed plan |
| `/orders/{id}/advance-status/` | POST | one rung up the ladder; gated at `packed` |
| `/orders/{id}/packing-list/` | GET | the plan as `.xlsx`; 400 while the order has no cartons |

`GET /orders/{id}/packing/` returns everything the packing screen needs to render
itself in a single response.

### Display (§10)

| Endpoint | Methods | Notes |
|---|---|---|
| `/display-products/` | CRUD | own catalogue; no box, no parts |
| `/pack-templates/` | CRUD | items written in the same request; `?is_library=true` for the picker |
| `/stores/` | CRUD | outlets under a merchant; `?merchant=` for one chain's |
| `/display-orders/` | CRUD | nested `lines`, each naming a `store` |
| `/display-orders/{id}/packing/` | GET | `stores` overview always; `?store=` adds that store's steps, remaining, applicable templates, reconciliation and copy targets |
| `/display-orders/{id}/cartons/` | GET | the boxes, paginated; `?step=N` or `?store=N` |
| `/display-orders/{id}/steps/` | POST | apply a template to one `store`; `count` defaults to the computed maximum |
| `/display-orders/{id}/steps/{seq}/` | PATCH, DELETE | re-count or drop a step; replays everything after it and returns `adjustments` |
| `/display-orders/{id}/replicate/` | POST | copy one `store`'s steps onto every identical unpacked store (§10.4.2) |
| `/display-orders/{id}/advance-status/` | POST | as Hardgoods |
| `/display-orders/{id}/packing-list/` | GET | `.xlsx`, blocked by store per §10.8 |

`POST /steps/` without a `count` applies the maximum — the common case, and the
one that makes the loop a single click per template.

`GET /packing/` deliberately **excludes** the cartons. The Hardgoods equivalent
returns everything in one response, which at 1 200 cartons is already a 393 KB
payload; a Display order runs larger still. The screen works in steps and drills
into `/cartons/` for one run at a time.

`applicable_templates` carries each library template's current capacity against
what remains, so the picker can show "TPL-001 · fits 36×" without a round trip
per template.

**Not yet implemented:** authentication (the API is currently open).

---

## 10. The Display module

Store decor — wreaths, garlands, bows, ornaments. Lives in `apps/display` with
its own tables. It shares the arithmetic with Hardgoods and nothing else.

### 10.1 Why it is a separate app

Hardgoods packing is **arithmetic**. A product's recipe determines its cartons
and auto-pack computes them; there is one right answer.

Display packing is a **judgement**, made by a person one box design at a time,
against whatever the order has left. There is no single right answer, and the
tail never comes out even.

| | Hardgoods | Display |
|---|---|---|
| Carton origin | the **product** owns its box | the **template** owns the box |
| Carton contents | one product, or one part | several different pieces |
| Packing logic | split by parts / `pack_per_box` | apply human-authored templates |
| The plan is | a list of cartons | a list of **steps** that generate cartons |
| Right answer | computable | chosen, then recorded |

Sharing tables would put a `kind` filter on every query and make each Display
change a Hardgoods regression risk, in exchange for reusing some columns. The
two modules share `apps/common` — `calc.py` and the `PackSpec` block — which is
where drift would actually be dangerous.

Order lines are identical in shape to Hardgoods: `{product, quantity, color}`,
one address per order. There are no stores and no channels.

**Supersedes D2 for Display.** D2 split `CartonContent` off `Carton` partly so
Display could share the table. Display now has its own. The split remains right
on its own merits — a Hardgoods carton still needs `part_id` for D3 — but that
second rationale no longer applies.

### 10.2 The packing loop

The merchant already knows how to pack the goods. The app's job is to record
that decision and do the counting.

```
   1. user defines a template     "30 bows + 5 wreaths, in this box"
   2. app computes how many fit    min over products of ⌊remaining ÷ required⌋
   3. user accepts or lowers it    28 proposed; 27 if it makes a rounder tail
   4. cartons materialise, remaining demand drops
   5. app shows what is left       repeat until nothing remains
```

The wall in step 2 is exactly:

```
MAX APPLICATIONS = min over pieces p in T of  ⌊ remaining[p] ÷ T[p] ⌋
```

A piece is `(product, part)` — see §10.4.1. For a catalogue with no multi-part
products this reads exactly as "per product", which is what it was until parts
arrived.

Worked, for an order of 840 bows, 96 ornament sets, 140 wreaths, 158 garlands:

| # | Template | Count | Consumes | Remaining after |
|---|---|---|---|---|
| 1 | 30 bows + 5 wreaths | 28 | 840 BOW, 140 WRT | 96 ORN · 158 GRL |
| 2 | 12 ornament sets + 6 garlands | 8 | 96 ORN, 48 GRL | 110 GRL |
| 3 | 6 garlands | 18 | 108 GRL | 2 GRL |
| 4 | 2 garlands *(one-off)* | 1 | 2 GRL | — |

Step 2 is capped by the ornament sets (`⌊96/12⌋ = 8`), not the garlands
(`⌊158/6⌋ = 26`). Step 1 happens to exhaust both of its products at once.

Two rules keep the loop terminating: every `PackTemplateItem.quantity` is at
least 1, and a template must consume at least one unit of something still
remaining. Without the second, a template that fits zero times applies forever.

### 10.3 The plan is a list of steps, not a pile of cartons

`PackStep` is the unit of planning. The four rows above **are** the plan; the
cartons are their output.

*Rationale:* the loop is greedy, and a greedy choice made early is only revealed
as wrong several rounds later. The two stranded garlands above are not fixed at
step 4 but at step 3: a 10-per-box template divides the 110 garlands exactly,
giving 11 cartons and no tail where 6-per-box gave 18 cartons plus a one-off.
Eight fewer boxes, found by changing a step already taken. Steps make that edit
expressible: change one, replay from there.

It also keeps the plan small. A step list stays four rows when the order runs to
a thousand cartons, so the packing screen renders steps and drills into boxes,
rather than paginating a carton table nobody reads.

Applying a step materialises real `DisplayCarton` rows, which stay individually
editable — the box actually used is not always the box planned, and a reweighed
carton must stick. Re-running a step discards hand edits inside its carton
range, and says so first. This mirrors Hardgoods auto-pack, which likewise
replaces rather than merges.

### 10.4 Data model

```
   DisplayProduct ◀─── PackTemplateItem ───▶ PackTemplate
          ▲                                       ▲
          │                                       │
   DisplayOrderLine ──▶ DisplayOrder ──▶ PackStep ┘
          │                   │              │
          │                   └──▶ DisplayCarton ──▶ DisplayCartonContent
          │                                 │
          └────────▶ masters.Store ◀────────┘
                          ▲
                          └──── PackStep
```

Every one of `DisplayOrderLine`, `PackStep` and `DisplayCarton` names a store.
That is not denormalisation for speed — see §10.4.2.

**DisplayProduct** — `style_no`(unique) · `style_name` · `description` · `category`→ ·
`customs_description` · `hsn_code` · `is_multi_part` · `status` ·
`product_weight_kg` · `{length,width,height}_in`

Its own catalogue, not `catalog.Product`. It has **no box of its own** — no
`PackSpec` block, no `pack_per_box`. Its dimensions are for customs and
fit-checking only. `masters.Category` and `masters.Merchant` are shared; they
are master data, not catalogue.

**DisplayProductPart** — `product`→ · `name` · `description` ·
`customs_description` · `hsn_code` · `product_weight_kg` ·
`{length,width,height}_in` · `sort_order`

A part owns no box either — it goes inside a template's carton exactly as a
whole product does. It exists because a product's parts need not travel in the
**same** carton: a tree's branch panels stack flat with each other while its
post is long and thin, and no box sensibly holds both.

`is_multi_part` selects which half of `DisplayProduct` is meaningful, on the
same terms as §5: when it is on, the product's own weight and dimensions stay
empty and each part carries its own, and customs description and HSN move to
part level. It is **fixed once the product is saved** — every template item,
step and carton already written against that style number assumed one shape.

### 10.4.1 Pieces

The unit the loop counts is a **piece**: `(store, product, part)`, where `part`
is null for a single-piece product. `PackTemplateItem` and
`DisplayCartonContent` both carry a nullable `part`, and every count in
`services.py` is keyed by the triple.

Ordering ten trees is therefore a demand for ten panel sets **and** ten posts,
each of which must find a box, and they need not find the same one.

*Why a piece and not a product:* a template that says "4 tree panels" must be
capped by the panels alone. Counting by product would let a box of panels
consume demand that only the posts can satisfy, and the order would read as
packed while half of every tree sat on the floor.

*Why the store is in the key:* §10.4.2. In short, thirty bows in Portland can
never fill a box bound for Austin, so the two demands must not be summed.

`PackTemplateItem` is unique on `(template, product, part)` with
`nulls_distinct=False` — without that, Postgres treats every whole-product row
as distinct from every other and the rule never bites. It carries **no** store:
a template is a box design, reusable by any store that happens to fit it.

### 10.4.2 Stores

A display order is one purchase order split across many outlets — a retailer
buys six hundred wreaths for fifty stores on one PO. So `DisplayOrderLine` is
`(order, store, product)`, unique on that triple, and stores need not share a
product mix: one may take wreaths and trees, its neighbour only wreaths.

**One carton never holds two stores' goods.** Everything else follows from that
single rule:

- `PackStep` names a store. A step packs for one destination.
- `DisplayCarton` names a store too, rather than reading it through the step,
  because `step` is nullable (`SET_NULL`) and a hand-built box still has to
  know where it is going.
- The greedy loop of §10.2 runs **inside** a store. `max_applications` is given
  one store's leftovers; `applicable_templates` is offered per store.
- Demand is never pooled. Sixty bows split thirty apiece means a
  sixty-per-box design fits *nobody* — and it must be refused, because the
  pooled total describes a carton that cannot legally exist.

Store *codes* belong to the merchant, not to us, so uniqueness is per merchant
(§5). `PROTECT` on every reference: a store with lines or cartons cannot be
deleted, because it is the address those boxes ship to.

**Replicating a plan.** Most of a fifty-store order wants the identical thing,
so packing one store and copying it is the difference between three clicks and
a hundred and fifty. `replicate_plan(order, source)` copies the source store's
steps onto every store whose demand matches it exactly **and** which has
nothing packed yet. A part-packed store is skipped rather than topped up —
copying onto work somebody has already started would mean guessing what they
meant.

**PackTemplate** — `code`(unique) · `name` · `merchant`→(null = global) ·
`order`→(nullable) · `remark` · `is_library` · `is_active` ·
`box_{length,width,height}_in` · `box_weight_kg` · `packing_material_weight_kg`

The box block is declared here rather than inherited from `PackSpec`. `PackSpec`
carries `product_weight_kg` and derives `net_weight_kg` from it, which is wrong
for a template: a template's net weight depends on what is actually inside the
box, and the same box holding 30 bows or 5 weighs differently. Inheriting a
property that lies is worse than repeating five field declarations.

That the box lives here at all is the inversion in §10.1 made concrete.

`is_library` separates designs worth keeping from tail-fillers, and `order`
scopes the tail-fillers. Templates are authored in-flow against live remaining
demand, so a one-off like *"2 garlands"* is normal — it must be usable on the
order it was written for, and must not silt up the picker on the next one.

The picker therefore offers three things: a global library design, a library
design for this merchant, or a one-off carrying this order.

```
Q(is_library=True, merchant__isnull=True)      global library
| Q(is_library=True, merchant=order.merchant)  this merchant's library
| Q(order=order)                               written for this order
```

*Rationale:* an earlier version filtered on `is_library` alone, so unticking the
box saved a design that then appeared nowhere — indistinguishable from losing
it. Scope and reusability are two questions, and they need two fields.

**PackTemplateItem** — `template`→ · `product`→ · `quantity` — unique on
`(template, product)`

**DisplayOrder** — `number`(unique, `DP-{year}-{0000}`) · `name` · `merchant`→ ·
`buyer_name` · `ship_{country,line1,line2,city,state,postal_code}` · `status`

Same status ladder as Hardgoods. `Order.generate_number` already takes a prefix.

**DisplayOrderLine** — `order`→ · `product`→ · `color` · `quantity` — unique on
`(order, product)`

**PackStep** — `order`→ · `sequence` · `template`→ · `count` — unique on
`(order, sequence)`

**DisplayCarton** — `order`→ · `carton_no` · `step`→(nullable) ·
`{length,width,height}_in` · `box_weight_kg` · `packing_material_weight_kg` ·
`gross_weight_kg` · `sort_order` — unique on `(order, carton_no)`

`step` is provenance, not constraint: contents may be edited away from what the
template says, and a `NULL` step means a hand-built carton.

The two packaging weights are **copied from the template** when the carton is
built rather than read back through `step`. A hand-built carton has no step, and
would otherwise have no way to account for its own padding.

**DisplayCartonContent** — `carton`→ · `product`→ · `description` · `quantity` ·
`unit` · `net_weight_kg`

`net_weight_kg` is that product's own weight only — the carton's padding sits on
the carton, because it belongs to the box rather than to any one thing inside
it. Splitting it across contents would be arbitrary, and the split would show up
on a customs line.

No `part` field — Display products have no parts, so D3 does not apply and
reconciliation is a plain sum.

### 10.5 Weights and volume

Unchanged in spirit from §4; only the source of the box moves.

```
CONTENT NET  = product_weight_kg × qty                     (per content row)

CARTON NET   = Σ content net  +  carton.packing_material_weight_kg
CARTON GROSS = CARTON NET     +  carton.box_weight_kg
CBM          = from the carton's own L × W × H
```

The sum over several products is the only new shape. It lives in
`apps/common/calc.py` as `mixed_carton_net_weight` / `mixed_carton_gross_weight`,
beside the existing per-carton helpers.

A template's weight is **never stored on the template**. The same box holding its
full 30 bows and holding 5 weigh different amounts, so net is always recomputed
from actual contents — D1, applied to the new path. `PackTemplate`
exposes `net_weight_kg` and `gross_weight_kg` as properties describing a *full*
box, for the template editor only; no carton reads them.

### 10.6 Carton numbering

Continuous across the order: `BOX-001`, `BOX-002`, … assigned in step order, so
each step owns one unbroken run. That keeps the packing list's ranges plain
rather than a rule to decode, for the reason given in §7.

**The store is a label on the carton, not a reset of the sequence.** One
shipment gets one run of numbers, whichever store each box is bound for. Per
store numbering would give a shipment fifty `BOX-001`s, and the first
duplicate is the first miscount.

**Numbers are never reassigned.** Editing step 4 rebuilds the cartons from step 4
onward, and they continue from the highest number still standing; everything
before keeps the number already written on the box. Deleting a middle step
therefore leaves a gap, which is fine — §7 already prints gapped runs by naming
each one (`BOX-001 – BOX-003, BOX-007`).

*Rationale:* an earlier draft renumbered on every edit and froze that at
`packed`. Not renumbering at all is strictly better — a number on a physical
carton can never move, at any status, and the packing list already handles the
gaps. Step *sequences* do close up (1, 2, 3), since those are a planning
artefact nobody writes on a box.

### 10.7 Reconciliation and blockers

Reconciliation is per store and product. A single-piece product is a plain sum
of its content quantities. A multi-part product counts each part separately and
takes the **minimum**, exactly as D3 does for Hardgoods: twenty panel sets and
eighteen posts is eighteen trees, not nineteen. That is both true and
actionable — go and find two posts.

One product ordered by two stores is **two rows**, not one total: twenty-four
wreaths in Portland say nothing about Austin, and a combined figure would read
as fine while one store sat empty. `quantity_mismatch` names the store for the
same reason — an unfinished store has to be findable, not merely implied by a
wrong total.

All five Hardgoods blockers apply unchanged — `missing_carton_no`,
`duplicate_carton_no`, `missing_dimensions`, `gross_below_net`,
`quantity_mismatch`. Unpacked remainder needs no new code: it is
`quantity_mismatch` by another name.

Display adds a **warning** tier — advisory, never blocking:

| Code | Condition |
|---|---|
| `template_capacity_exceeded` | contents edited beyond what the step's template holds |
| `poor_fill` | contents occupy far less than the box; freight spent on air |

*Rationale:* a template encodes something a human physically packed, so the app
warns on its own arithmetic and never overrules it. Real 3D fit is not solved
here — volume comparison cannot know how shapes nest.

This adds a `warnings` array beside `blockers` in the packing response, which
the frontend must read.

### 10.8 Packing list

The §7 document, with one change: cartons merge on their **whole content set**
rather than on a single content row. §7 says a multi-content carton never
merges, which under Display would merge nothing and print a row per box.

Every carton from one step is identical by construction, so the sheet comes out
at roughly **one row per step** — four rows for the worked example above, which
ships 55 cartons. That
is the same document a customs officer already reads, and it is why steps are
the right unit of planning as well as of editing.

**Blocked by store.** Each store opens with a banner carrying its name and
address, carries its own rows, and closes with its own subtotal; the order
total comes last. That is the shape the sheet is *used* in — the warehouse
picks a pallet per store, not per order.

The grouping, the carton-range notation and the column layout are shared with
Hardgoods in `apps/common/packing_sheet.py`. Only the blocking is particular to
Display. A shipping desk reading one document after the other should not have
to learn two conventions.

The order total sums the store blocks **by naming each range**, not by spanning
them: a single span would cross the subtotal rows and count every carton twice.
Totals are written as formulas rather than values so the sheet stays true if
somebody edits a quantity after it leaves here — which is exactly why the
double-count would otherwise have survived a proofread.

### 10.9 Still open

- Photos for display products — the `ProductImage` owner constraint is a CHECK
  over `product`/`part` and would need a third owner, or its own table.
- Excel import of the order lines. Typing a fifty-store grid by hand is the
  obvious next bottleneck now that the bulk-fill covers only the uniform case.
- Whether a display order still needs its own ship-to address. The columns are
  retained but unused: stores carry the addresses, and the order-level block no
  longer appears on the entry form. It may yet earn its keep as a bill-to.
- A per-store packing list as a separate document, if a store's copy has to
  travel with its own pallet rather than the whole sheet going to customs.
- Whether a template may be edited after an order has used it. The provenance
  link would then misdescribe boxes already shipped — the same hazard as
  `is_multi_part`, and it probably wants the same answer.

---

## 11. Open items

### Resolved since the brief

| Brief item | Resolution |
|---|---|
| Net/gross formula | Confirmed against the mockup's own worked example: Net = Product + Packing Material; Gross = Net + Box |
| Units | Inches and kilograms (D4) |
| Terminology | Section 3 is now the agreed vocabulary |
| Orders / Packing review | Rebuilt against the confirmed terminology; reconciliation corrected (D3) |

### Still open

1. **Post-save redirect** — where Save on the product form navigates. Product list
   is the working assumption.
2. **Weighing workflow** — what happens when weight is unknown at product-creation
   time. Determines whether weight fields may be null, which affects auto-pack
   output and blocker behaviour.
3. **Photo management depth** — upload, camera capture, set-main and delete are
   built. Whether rotation, cropping or client-side downscaling are needed is
   still open; camera captures currently upload at the sensor's full resolution.
4. **Authentication and roles** — the sidebar shows a user; no auth exists. Must
   be resolved before any deployment.
5. **Order status coverage** — no `cancelled` or `on-hold` state. Retrofitting an
   enum later is disruptive.
6. **Two colours of one style in one order** — colour sits on the order line and
   `(order, product)` is unique, so a single order cannot ask for the same style
   in two finishes. Supporting it means colour on `CartonContent` and a
   reconciliation keyed by colour as well as part.
7. **Photo storage** — local `MEDIA_ROOT` in development; needs an object store
   before deployment.

---

## 12. Build order

Vertical slices — database, API and screen for one feature at a time.

- [x] **0** Frontend scaffold — Next.js 16, Tailwind v4, design tokens, `api.ts`, `calc.ts`, types
- [x] **0b** Backend — models, admin, API, packing engine, seed data
- [x] **0c** Docker — compose for db + api + web, multi-stage images
- [x] **1** App shell + Categories screen — establishes the pattern
- [x] **2** Merchants screen
- [x] **4** Product form — single-box path
- [x] **5** Product form — multi-part path
- [x] **6** Photo upload — product and part galleries, file picker or in-app camera
- [x] **7** Orders — list and create
- [x] **8** Packing workspace
- [x] **9** Packing list document — Excel, per order, one row per thing packed
- [ ] **10** Authentication

Display (§10), each slice usable before the next starts:

- [x] **11** `apps/display` — `DisplayProduct`, admin, API
- [x] **12** `PackTemplate` + items — model, admin, API
- [x] **13** `DisplayOrder` + lines — model, admin, API
- [x] **14** The step engine — `PackStep`, apply, re-count, delete, replay,
      reconciliation, blockers, warnings. API only, verified against the §10.2
      worked example by `seed_display` and by `apps/display/tests.py`.
- [x] **15** Display product, template and order screens (frontend)
- [x] **16** Packing screen — the step loop, remaining demand, in-flow templates
- [ ] **17** Packing list — set-based carton merging (§10.8)
