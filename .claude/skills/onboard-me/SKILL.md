---
name: onboard-me
description: >-
  Onboard a NEW user into the ATS by choosing the application-category vocabulary
  they actually apply under. Use when the user wants to set the tracker up for
  their own field, says "onboard me", "set up my categories", "I'm a
  finance/product/design person, fix the categories", or asks what job categories
  the app should show. Interviews the user for their role categories and persists
  them so the web app's dropdowns and charts reflect their field instead of the
  built-in defaults. (Scaffold: today this covers categories only; résumé / profile
  / config setup will join it later.)
---

# Onboard a new user

Right now this skill does ONE thing: replace the built-in default category list (a
general starter set) with the categories the user actually applies under, so a
finance or product user never sees engineering labels in the tracker.

## Steps

1. **Ask** what kinds of roles they're targeting and turn it into 3–8 short category
   labels in THEIR words. Examples:
   - finance → `Investment Banking, Private Equity, Equity Research, Sales & Trading, Others`
   - product → `Product, Growth, Product Marketing, Others`
   Keep an `Others` catch-all. Don't invent categories they didn't imply.
2. **Persist** them with the bundled script (writes the shared SQLite directly via the
   worker DB layer — the web UI reflects it immediately):
   ```bash
   python .claude/skills/onboard-me/scripts/set_categories.py "Cat A,Cat B,Others"
   ```
3. **Confirm** the one-line output (`set N categories: …`). Tell them the list now
   appears in the Add-application form, the Mark-Applied dialog, the table filter, and
   the category donut — and that they can edit it anytime from the web app's
   **Categories** button.

## Notes

- Categories are free-form labels; there is no fixed enum. Removing one later does not
  relabel applications already filed under it.
- Requires the shared DB to exist (`make db-push`).
