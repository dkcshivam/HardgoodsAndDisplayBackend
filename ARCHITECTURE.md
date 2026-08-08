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

**In scope now:** the Hardgoods module — furniture and homeware.

**Deferred:** the Display module — store decor (wreaths, bows, garlands). Its
screens and sample data are designed but not built. It differs structurally
(see §10) and the schema already accommodates it.

**Not yet designed:** authentication and roles, packing-list document generation,
photo editing beyond upload and set-main.

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

### catalog

**Product** — `style_no`(unique) · `description` · `category`→ ·
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
merchant asked for this time, and the packing list prints it. One colour per
product per order — two finishes of one style in a single order would need
colour on `CartonContent` too, and is not supported.

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

*Rationale:* Hardgoods puts one product (or one part) per carton, so flattening
contents onto `Carton` would work today. Display packs several different products
into one carton from a template, and would not. Splitting later means rebuilding
the packing screen, the API and migrating live data.

*Cost:* one extra table and one join. Accepted.

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

**Multi-part product** — for each ordered unit, emit one carton per part.
Quantity 1, box and dimensions from that part, gross from that part's weights.
*3 tables × 2 parts = 6 cartons.*

**Single-box product** — split quantity by `pack_per_box`:
`ceil(qty / pack_per_box)` cartons, each holding `min(pack_per_box, remaining)`.
*6 chairs at 2/box = 3 cartons.*

Carton numbers run sequentially `CTN-001`, `CTN-002`, …

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
per carton content —

```
Carton No · Style No · Color · Description · Qty · Net Wt · Gross Wt · L · W · H · CBM
```

Colour comes from the order line for that product. Carton-level figures — number,
gross weight, dimensions, CBM — sit on the row that *opens* the carton and are
blank on its remaining rows, so the totals row can sum a column without counting
a carton twice. Dimensions are deliberately not totalled. Totals are written as
`SUM()` formulas so the sheet stays true if someone edits a row.

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

### Display (deferred)

| # | Screen | Status |
|---|---|---|
| 13 | Display Products — list | Not built |
| 14 | Display Stores — list | Not built |
| 15 | Display Pack Templates — list | Not built |
| 16 | Display Orders — list | Not built |
| 17 | Display Order — store picker | Not built |
| 18a | Display Order — matrix entry (product × store) | Not built |
| 18b | Display Order — Excel import (alternative path) | Not built |
| 19 | Display Packing — template auto-pack with remainders | Not built |

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

**Not yet implemented:** authentication (the API is currently open).

---

## 10. The Display module

Deferred, but the schema is shaped to accept it without migration pain.

Structural differences from Hardgoods:

| | Hardgoods | Display |
|---|---|---|
| Destination | one address per order | **many stores** per order |
| Order line | `{product, qty}` | `{product, store, qty}` — a matrix |
| Carton contents | one product or part | **several different products** |
| Packing logic | split by parts / pack-per-box | match a reusable **pack template** |
| Entry paths | product picker | store picker → matrix, or Excel import |

Additional entities required: `Store` (code and/or name, merchant, channel, city,
country), `Channel` (USA Collection Stores, UK/EU Collection Stores, Wholesale,
Bulk Presents, USA Movement Stores), `PackTemplate` (name, box L/W/H, remark) and
`PackTemplateItem` (`{product, qty}`).

Display auto-pack runs per store against matched templates and reports
**remainders** — units that do not fill a template box and need manual packing.

D2 (`CartonContent` as a separate table) exists specifically so that Display
cartons can hold mixed contents on the same schema.

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
- [x] **9** Packing list document — Excel, per order, colour from the order line
- [ ] **10** Authentication
- [ ] **11** Display module
