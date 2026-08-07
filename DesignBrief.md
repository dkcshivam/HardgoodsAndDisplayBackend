# Packing Management App — Design Brief

## Scope right now
Building the **Hardgoods** module only. Other categories are out of scope until Hardgoods is settled, but the app shell, navigation, and screen patterns below are being decided with future categories in mind.

## App Shell
- Left nav + main content area, with a command palette (search), confirm dialogs, and toast notifications as shared overlay patterns.
- Screens are conditionally rendered sections inside one shell (Dashboard, Hardgoods Products, Hardgoods Product Form, Hardgoods Orders, Hardgoods Order Create, Hardgoods Order Detail/Packing).

## Screen Map (current build — `Packing App.dc.html`)

1. **Dashboard** — "Needs attention" panel + "Recent activity" feed.
2. **Hardgoods Products (list)** — flat list, Category as a column (not a grouping), no custom name in list view.
3. **Hardgoods Product Form** — sectioned form: Identity → Dimensions & weight → Box (single-box path) → Parts/split packing (multi-part path) → Images → Product group.
4. **Hardgoods Orders (list)**
5. **Hardgoods Order Create** — Order details → Shipping address → Products.
6. **Hardgoods Order Detail** — tabbed: Details tab (order + ship-to + products ordered) and Packing tab (packing workspace with a footer showing blockers, summary, and save).
7. Shared: Command palette, confirm dialog, toast stack.

Note: the exploratory mockups in `Packing App Mockups.dc.html` (single item form, multi-part form, category screens, first-time setup) are the design lab for what eventually lands in the sections above — patterns validated there (vertical flow, per-part full data, auto-calculated weights) should be ported into the real form here.

## Key Decisions So Far

**Product list**
- No category-wise grouping — Category is a column like any other field.
- Custom/trade name only shown inside the product record, not in the list.

**Product form — general**
- Strict vertical, single-column flow: one field or logical group per row. Dimension groups (L/W/H, or L/W/H + CBM) may share a row; every weight field (part weight, box weight, packing material weight, net weight, gross weight) gets its own row. (Standing rule, see `CLAUDE.md`.)
- Customs Description Name and HSN Code are captured — at product level for single-box items, at part level for multi-part items.
- Category dropdown has a refresh action so a user mid-form can pull in a newly-added category without losing form state.

**Single-box item**
- Fields: Style No, Category, Description → Customs Description Name, HSN Code → Box Dimensions (L/W/H + auto CBM) → Product Weight → Box Weight → Packing Material Weight → Net Weight (auto) → Gross Weight (auto) → Product Photos → Save.

**Multi-part item**
- Product level keeps **assembled dimensions and weight** (for reference — the finished, put-together item), separate from **shipping data**, which lives entirely at part level since parts ship in separate boxes.
- Each part carries the same depth of data as a single-box product: part name, part description, Customs Description Name, HSN Code, part dimensions, part weight, box dimensions (+ auto CBM), box weight, packing material weight, net/gross weight (auto), and multiple photos (different angles, one marked main).
- Parts are NOT a dense multi-column table — each part is a card, collapsed by default, expanding in place into the full vertical editor. Avoids a separate navigation per part and avoids cramming many columns into one row.
- Product Photos section sits above the Parts section.
- Category is asked once at product level, not repeated per part.

**Weight model (single box and per-part, same shape)**
- User enters: Product Weight (bare item), Box Weight (carton alone), Packing Material Weight (padding/filler).
- App auto-calculates: Net Weight and Gross Weight from the above. *(Exact formula not yet confirmed — see Open Items.)*

**Save flow**
- Save action lives at the bottom of the form, not the header.
- Saving redirects to another page (destination not yet confirmed — likely the product list).

**First-time setup**
- A short step before the full form: Style No, Category, Description, then a choice between "Single item, one box" vs "Packed in multiple parts" — this choice branches into the single-box form or the multi-part form.

## Terminology (please review/confirm)

| Term | Current meaning |
|---|---|
| Style No | Unique product/SKU identifier |
| Category | Product category — set once per product, not per part |
| Description | Internal/trade name |
| Customs Description Name | Name used on customs declarations, may differ from Description |
| HSN Code | Harmonized System Nomenclature code for customs classification |
| Product Weight | Weight of the bare item/part, no packaging |
| Box Weight | Weight of the shipping carton alone |
| Packing Material Weight | Weight of padding/filler inside the box, separate from the box itself |
| Net Weight | Auto-calculated (formula tbd) |
| Gross Weight | Auto-calculated, includes box (formula tbd) |
| CBM | Cubic meter volume of the shipping box, auto from box L×W×H |
| Assembled Dimensions/Weight | Product-level size/weight of the finished, fully assembled item — kept for reference even when shipped disassembled |
| Part | An individually packed sub-component of a multi-part product, with its own full shipping/customs data |

## Open Items
1. **Net/Gross weight formula** — confirm exactly which fields sum into each (working assumption: Net = Product + Packing Material; Gross = Net + Box).
2. **Post-save redirect destination** — confirm where Save takes the user.
3. **Weighing workflow** — need a plan for when weight isn't known upfront: a "weigh now" flow vs. manual entry fallback, and whether this differs for parts vs. single items.
4. **Photo management depth** — confirm whether rotation/cropping/deletion are needed beyond upload + set-main.
5. **Category List / Category Add/Edit** — screens exist in mockups but not yet ported to/aligned with the working app.
6. **Inactive Products view** — same as above.
7. **Orders + Packing tab** — already built in the working app; not yet reviewed against the same terminology/vertical-flow rules used for the product form — worth a pass once Hardgoods product form is finalized.

## Next Steps
1. Confirm terminology and weight formulas above.
2. Port validated mockup patterns (vertical flow, per-part card, product-photos-above-parts) into `Packing App.dc.html`'s real Product Form.
3. Design Category List / Add-Edit and Inactive Products screens against the same pattern, then port them in.
4. Decide the post-save redirect.
5. Resolve weighing-workflow and photo-editing open items.
6. Review Orders/Packing screens for terminology and layout consistency once the product form is locked.
