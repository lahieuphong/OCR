import {afterEach} from "vitest";
import {cleanup} from "@testing-library/react";

afterEach(() => cleanup());
if (typeof window !== "undefined") {
  // jsdom has no native dialog UI. Real focus trapping and confirmation are also exercised in Electron.
  HTMLDialogElement.prototype.showModal = function () {this.setAttribute("open", "");};
  HTMLDialogElement.prototype.close = function () {this.removeAttribute("open");};
  HTMLElement.prototype.scrollIntoView = function () {};
  globalThis.ResizeObserver = class {observe() {} unobserve() {} disconnect() {}};
}
