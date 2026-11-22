---
name: ui-design
description: Create or modify plottwist pages and interactions with an academic, minimal visual style focused on MATLAB input, generated Python, and plots.
---

# plottwist UI design

Build a focused academic computing workspace. Read the existing templates and
CSS before editing, preserve established patterns, and stay within the requested
feature scope. Use Django Templates, Tailwind, and vanilla JavaScript.

## Layout and visual language

- Lead with the MATLAB input and the action that produces results. Keep the
  application name and short description compact; avoid dashboard navigation,
  sidebars, promotional sections, and oversized cards.
- At desktop widths, use adjacent source and results areas when space allows.
  On narrow screens, stack source, generated code, then plots in reading order.
- Use a warm neutral background, dark readable text, quiet borders, and one
  restrained green accent for primary controls and focus. Reserve error colours
  for actual errors. Avoid gradients, glass effects, decorative animation, and
  unnecessary shadows.
- Keep spacing on a consistent 4/8px scale, with 16–24px within sections and
  24–32px between them. Use modest corner radii and compact section headings.
- Use a system sans-serif for labels/body, a monospace stack for code, and an
  optional restrained serif wordmark. Body and editable code should be at least
  14px; use smaller text only for secondary metadata.

## Forms and controls

- Label every input visibly. Use a native multiline textarea for MATLAB until
  a richer editor has a concrete need; disable spellcheck and use readable line
  height, preserved whitespace, and local horizontal scrolling for long lines.
- Distinguish editable source from read-only generated Python with headings and
  surface styling. Never rely on colour alone or use a placeholder as a label.
- Give the Run control clear visual priority and a comfortable target of at
  least 44px. Use semantic buttons, visible keyboard focus, and clear disabled
  styling. Place an explanation near any unavailable action.
- Add controls only when their behavior exists. Keep unfinished actions honest;
  do not simulate translations, executions, or successful outputs.

## Feedback and results

- Use short, specific status text near the action/result it describes. Empty
  states should identify what belongs in the area without fabricated results.
- When loading is implemented, prevent duplicate submissions, preserve input,
  and announce status with a polite live region. Avoid decorative motion.
- When errors are implemented, state what failed and the useful next action;
  preserve source code and associate field errors with their inputs.
- Present generated Python as selectable, read-only `pre`/`code` output with
  internal overflow. Display figures on neutral surfaces with clear captions;
  preserve plot aspect ratios, readable axes, and separate multiple figures.

## Responsive behavior and accessibility

- Keep containers shrinkable (`min-width: 0`) and code overflow within its pane.
  Check approximately 360px and 1280px widths and 200% zoom; avoid page-wide
  horizontal scrolling. Let section controls wrap when necessary.
- Use landmarks, ordered headings, associated labels, and a skip link. Maintain
  readable contrast and visible focus; status must be understandable without
  colour. Hide decorative icons from assistive technology and label useful ones.
- Keep the primary workflow understandable without instructions. Verify actual
  browser layout, keyboard access, empty/disabled states, and static asset loading
  before reporting a UI change complete.
