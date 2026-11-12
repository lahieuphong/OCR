import {afterEach} from "vitest";
import {cleanup} from "@testing-library/react";
import {iconRuleViolations} from "./iconRule.js";

// Every screen a test renders must follow the icon rule (iconRule.js, docs/UI_ICONS.md).
afterEach(() => {
  const problems = typeof document === "undefined" ? [] : iconRuleViolations(document.body);
  cleanup();
  if (problems.length) throw new Error(`Icon rule (docs/UI_ICONS.md):\n${[...new Set(problems)].join("\n")}`);
});
if (typeof window !== "undefined") {
  // jsdom has no native dialog UI. Real focus trapping and confirmation are also exercised in Electron.
  HTMLDialogElement.prototype.showModal = function () {this.setAttribute("open", "");};
  HTMLDialogElement.prototype.close = function () {this.removeAttribute("open");};
  HTMLElement.prototype.scrollIntoView = function () {};
  globalThis.ResizeObserver = class {observe() {} unobserve() {} disconnect() {}};
}
