// @vitest-environment jsdom
// The icon rule (docs/UI_ICONS.md): one icon set, lucide, in the web UI and in the desktop app's own windows.
import {readdirSync, readFileSync} from "node:fs";
import {createRequire} from "node:module";
import {dirname, join, resolve} from "node:path";
import {fileURLToPath} from "node:url";
import {describe, expect, test} from "vitest";
import {render} from "@testing-library/react";
import {icons} from "lucide-react";
import {ICON_GLYPHS, iconRuleViolations} from "./iconRule.js";

// Paths from the file itself: under jsdom, URL is not Node's.
const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(HERE, "..");
const ELECTRON = resolve(HERE, "../../../../../desktop/electron");

function page(html) {
  return new DOMParser().parseFromString(html, "text/html");
}

describe("iconRuleViolations", () => {
  test("accepts icon + label, a named icon-only button and a value control", () => {
    const {container} = render(<>
      <button><icons.Download/>Xuất JSON</button>
      <button aria-label="Sao chép JSON"><icons.Copy/></button>
      <details><summary><icons.ChevronRight/>Chi tiết</summary></details>
      <button className="page-pick">Trang 1</button>
    </>);
    expect(iconRuleViolations(container)).toEqual([]);
  });

  test("flags a text-only button, a character icon, a bare disclosure and an unnamed icon-only button", () => {
    const {container, unmount} = render(<>
      <button>Đóng</button>
      <button aria-label="Xóa">×</button>
      <details><summary>Chi tiết</summary></details>
      <button><icons.Copy/></button>
    </>);
    const problems = iconRuleViolations(container);
    expect(problems.filter(p => p.startsWith("no lucide icon"))).toHaveLength(3);
    expect(problems.filter(p => p.startsWith("character used as an icon"))).toHaveLength(1);
    expect(problems.filter(p => p.startsWith("icon-only button without aria-label"))).toHaveLength(1);
    unmount();  // this screen breaks the rule on purpose: gone before the after-test check (setup.js)
  });
});

test("no character stands in for an icon in the UI sources", () => {
  const files = readdirSync(SRC, {recursive: true}).filter(name => /\.jsx$/.test(name) && !/\.test\.jsx$/.test(name));
  expect(files.length).toBeGreaterThan(5);
  const found = files.flatMap(name => readFileSync(join(SRC, name), "utf8").split("\n")
    .map((line, index) => ICON_GLYPHS.test(line) ? `${name}:${index + 1}: ${line.trim()}` : null).filter(Boolean));
  expect(found).toEqual([]);
});

describe("the desktop app's own windows use the same lucide icons", () => {
  const status = page(readFileSync(join(ELECTRON, "status.html"), "utf8"));
  const splash = page(createRequire(import.meta.url)(join(ELECTRON, "lib", "splash.js")).SPLASH_HTML);
  const pascal = name => name.replace(/(^|-)(\w)/g, (_, __, c) => c.toUpperCase());
  const shape = svg => [...svg.children].map(node => `${node.tagName.toLowerCase()} ${[...node.attributes].map(a => `${a.name}=${a.value}`).sort().join(" ")}`);

  test("status window: every button and disclosure has an icon, no character icons", () => {
    expect(status.querySelectorAll(".actions button")).toHaveLength(3);
    expect(iconRuleViolations(status.body)).toEqual([]);
    expect(ICON_GLYPHS.test(status.body.textContent) || ICON_GLYPHS.test(splash.body.textContent)).toBe(false);
  });

  test.each([["status.html", status], ["splash", splash]])("%s: each inline icon is lucide's own", (_, doc) => {
    const inline = [...doc.querySelectorAll("svg[data-lucide]")];
    expect(inline.length).toBeGreaterThan(1);
    expect(doc.querySelectorAll("svg:not([data-lucide])")).toHaveLength(0);
    for (const svg of inline) {
      const Icon = icons[pascal(svg.dataset.lucide)];
      expect(Icon, svg.dataset.lucide).toBeTruthy();
      const {container, unmount} = render(<Icon/>);
      const reference = container.querySelector("svg");
      expect(shape(svg), svg.dataset.lucide).toEqual(shape(reference));
      for (const attribute of ["viewBox", "fill", "stroke", "stroke-linecap", "stroke-linejoin"]) {
        expect(svg.getAttribute(attribute), `${svg.dataset.lucide} ${attribute}`).toBe(reference.getAttribute(attribute));
      }
      expect(svg.classList.contains("lucide")).toBe(true);
      unmount();
    }
  });
});
