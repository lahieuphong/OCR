// The app's icon rule (docs/UI_ICONS.md), checked after every rendered test (setup.js):
// every button and every disclosure (<summary>) shows a lucide icon, an icon-only button has a name,
// and no character stands in for an icon (×, ✓, ☰, ▸…).

// Controls whose visible label IS the value they pick or open, not an action: they stay text only.
export const TEXT_ONLY_CONTROLS = [
  ["[role=option]", "a value of a dropdown"],
  [".select-queued-file", "a row of the document list (number, status dot, name)"],
  [".open-document", "a document name shown as a link"],
  [".queue-filter", "a filter chip: status and its count"],
  [".page-pick", "a page number: Trang N"],
  [".number-code-choices button", "a line number: Dòng N"],
  [".app-menu-zoom-value", "the display size: 100%"],
];

// Characters that only make sense as an icon. Text such as "40 × 40 mm" lives in data, not in controls.
export const ICON_GLYPHS = /[×✕✖✓✔☰≡⚠▶▸►▾▼▴▲◀◂↻⟳⬇⬆✎✏⋮⋯]/u;

const textOnly = element => TEXT_ONLY_CONTROLS.some(([selector]) => element.matches(selector));
const describe = element => element.outerHTML.replace(/\s+/g, " ").slice(0, 160);

export function iconRuleViolations(root) {
  const problems = [];
  for (const element of root.querySelectorAll("button, summary")) {
    const text = element.textContent.trim();
    if (ICON_GLYPHS.test(text)) problems.push(`character used as an icon: ${describe(element)}`);
    if (element.matches("button") && textOnly(element)) continue;
    if (!element.querySelector("svg.lucide")) problems.push(`no lucide icon: ${describe(element)}`);
    else if (element.matches("button") && !text && !element.getAttribute("aria-label")) problems.push(`icon-only button without aria-label: ${describe(element)}`);
  }
  return problems;
}
