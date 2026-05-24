---
id: print-format-authoring
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Authoring or modifying a Print Format (Jinja or Designer) for any DocType"
scope: [agent:architect, agent:backend-specialist, agent:security-reviewer]
foundational: false
domain: reporting
security_score: 100
supersedes: []
---

# Print Format Authoring

How to author Print Formats — both Jinja-based and Designer-based — for invoices, POS receipts, payroll slips, and parcel labels on this bench. Special attention to **XSS in Jinja `| safe` misuse** because every print format renders user data.

## When to Load
- Adding a Print Format for any DocType
- Modifying an existing format for `noviznaerp_payroll` salary slip, `novizna_pos` POS Invoice, or `cargo_management` parcel label
- Reviewing Jinja for `| safe` misuse
- Debugging a wkhtmltopdf rendering issue (footer cut off, page break, etc.)

## Key Concepts

1. **Jinja vs Designer** — Jinja: full HTML/CSS control, programmable. Designer: drag-and-drop, limited but safer.
2. **`frappe.format_value(value, df)`** — formats a value per the DocType field's metadata (date, currency, link).
3. **`| safe` filter** — disables HTML escaping. Dangerous on user-controlled fields. Use only on values you produced.
4. **Letterheads** — separate `Letter Head` DocType; can include header/footer HTML; combined at render time.
5. **wkhtmltopdf** — the rendering engine. Quirks: page breaks, footer height, image base64 inlining, missing fonts.
6. **`<div class="page-break"></div>`** — explicit page break marker.
7. **Per-print-format CSS** — declared in the format's `css` field; injected into the rendered HTML.

## Patterns

### Pattern: Basic Jinja Print Format

**When:** Authoring a POS receipt for `novizna_pos`.

**Do:**
```html
{# Print Format: POS Invoice Thermal #}
<div class="receipt">
  <h2>{{ doc.company }}</h2>
  <p>Invoice: {{ doc.name }} &middot; {{ frappe.format_value(doc.posting_date, {"fieldtype": "Date"}) }}</p>
  <p>Customer: {{ doc.customer_name }}</p>

  <table style="width:100%; border-collapse: collapse;">
    <thead>
      <tr><th>Item</th><th>Qty</th><th>Rate</th><th>Amount</th></tr>
    </thead>
    <tbody>
      {%- for item in doc.items %}
      <tr>
        <td>{{ item.item_name }}</td>
        <td>{{ item.qty }}</td>
        <td>{{ frappe.format_value(item.rate, {"fieldtype": "Currency", "options": doc.currency}) }}</td>
        <td>{{ frappe.format_value(item.amount, {"fieldtype": "Currency", "options": doc.currency}) }}</td>
      </tr>
      {%- endfor %}
    </tbody>
  </table>

  <h3>Total: {{ frappe.format_value(doc.grand_total, {"fieldtype": "Currency", "options": doc.currency}) }}</h3>
  <p>{{ frappe.utils.money_in_words(doc.grand_total, doc.currency) }}</p>
</div>
```

`frappe.format_value` handles localization, currency symbol, and decimal precision uniformly.

**Don't (XSS recurrence):**
```html
<p>{{ doc.customer_notes | safe }}</p>
```
`customer_notes` is user-supplied. `| safe` lets `<script>alert(1)</script>` execute when the format renders in the desk preview. Use the default (escaped) rendering, or sanitize explicitly with `frappe.utils.sanitize_html`.

### Pattern: Conditional sections

**When:** Optional tax breakdown.

**Do:**
```html
{%- if doc.taxes %}
<h4>Taxes</h4>
<table>
  {%- for tax in doc.taxes %}
  <tr>
    <td>{{ tax.description }}</td>
    <td>{{ frappe.format_value(tax.tax_amount, {"fieldtype": "Currency", "options": doc.currency}) }}</td>
  </tr>
  {%- endfor %}
</table>
{%- endif %}
```

### Pattern: Page breaks for multi-page formats

**When:** Salary Slip with attendance table that may overflow.

**Do:**
```html
<div class="salary-summary">...</div>

<div class="page-break"></div>

<div class="attendance-detail">
  <table>...</table>
</div>
```

```css
/* In the format's CSS field */
.page-break { page-break-after: always; }
@media print {
  .receipt { font-family: 'Inter', sans-serif; }
}
```

### Pattern: Letterhead with header/footer

**When:** Invoices need company letterhead with logo header + bank details footer.

**Do:**
- Create or update a `Letter Head` doc (name e.g., "Novizna Default")
- Set `header` and `footer` HTML fields
- On Sales Invoice → set `letter_head = "Novizna Default"`
- Print Format renders inside the body region; letterhead wraps it

**Don't:** Put `<header>` / `<footer>` HTML inside the Print Format itself — wkhtmltopdf treats them as body content, not page headers; they appear once, not per page.

### Pattern: Safe rendering of HTML fields

**When:** A field's `fieldtype` is `Text Editor` and you want to render formatting.

**Do:**
```html
{{ frappe.utils.strip_html_tags(doc.description) }}      {# plain text #}
{# OR for trusted internal content only: #}
{{ doc.description | safe }}
```

Apply `| safe` only when the content's provenance is internal (controller-set, not user-entered).

## wkhtmltopdf Quirks (this bench)

- **Footer overlap** — set `margin-bottom` >= footer height in the letterhead's footer block CSS.
- **Page numbers** — use `<span class="page"></span>` / `<span class="topage"></span>` inside the footer for X/Y page numbering.
- **Missing fonts** — wkhtmltopdf can't access system fonts not embedded in CSS via `@font-face`. Use web-safe fallbacks (Helvetica, Arial).
- **Base64 images** — large logos as base64 bloat the PDF; reference via URL (`/files/...`).
- **CJK / RTL** — needs the appropriate font installed and declared.

## Common Pitfalls
- `| safe` on a user-supplied field (XSS) — Security Reviewer flags as MEDIUM (or HIGH if the field is rendered in a multi-user UI like POS).
- Hard-coded currency `$` symbols — breaks for non-USD; use `frappe.format_value` with the doc's currency.
- Forgetting `<meta charset="utf-8">` in the format HTML — non-ASCII characters render as mojibake.
- Embedding inline `<style>` tags repeatedly across formats — extract to the format's CSS field.
- Format references a field that was renamed on the DocType — silent empty render.
- Designer formats edited as raw JSON in git — easy to break the layout; prefer Jinja for any non-trivial format.

## References
- [`reporting/script-report-authoring`](./script-report-authoring.md) — sibling reporting skill
- [`security/review-checklist`](../security/review-checklist.md) — for the `| safe` XSS check
- [`erpnext-domains/pos`](../erpnext-domains/pos.md) — POS-specific receipt patterns
- [`erpnext-domains/hr-payroll`](../erpnext-domains/hr-payroll.md) — Salary Slip print format
