// @vitest-environment jsdom
import React from "react";
import {afterEach, beforeEach, expect, test, vi} from "vitest";
import {act, fireEvent, render} from "@testing-library/react";
import DocumentPreview, {paintDelay} from "./DocumentPreview.jsx";

const MB = 1048576;
beforeEach(() => {vi.useFakeTimers();});
afterEach(() => {vi.useRealTimers();});

const pass = ms => act(() => {vi.advanceTimersByTime(ms);});
const layers = () => Array.from(document.querySelectorAll(".preview-layer"), layer =>
  `${layer.querySelector("iframe, img")?.src.replace(/#.*$/, "").replace("http://localhost:3000/", "") || "cover"}:${layer.className.replace("preview-layer ", "")}`);
const frame = name => document.querySelector(`iframe[src^="blob:${name}"]`);
const pdf = name => ({url:`blob:${name}`, isPDF:true, size:0});

test("the first document waits behind an empty cover until it has had time to draw", () => {
  render(<DocumentPreview {...pdf("a")}/>);
  expect(layers()).toEqual(["cover:shown", "blob:a:loading"]);
  expect(frame("a").src).toBe("blob:a#toolbar=0");
  pass(4999);
  expect(layers()).toEqual(["cover:shown", "blob:a:loading"]);
  fireEvent.load(frame("a"));
  pass(199);
  expect(layers()).toEqual(["cover:shown", "blob:a:loading"]);
  pass(1);
  expect(layers()).toEqual(["cover:leaving", "blob:a:shown"]);
  pass(120);
  expect(layers()).toEqual(["blob:a:shown"]);
});

test("the document on screen stays until the next one has drawn, and that one is not reloaded", () => {
  const view = render(<DocumentPreview {...pdf("a")}/>);
  fireEvent.load(frame("a")); pass(200); pass(120);
  view.rerender(<DocumentPreview {...pdf("b")}/>);
  expect(layers()).toEqual(["blob:a:shown", "blob:b:loading"]);
  const loadingFrame = frame("b");
  fireEvent.load(loadingFrame); pass(199);
  expect(layers()).toEqual(["blob:a:shown", "blob:b:loading"]);
  pass(1);
  expect(layers()).toEqual(["blob:a:leaving", "blob:b:shown"]);
  pass(120);
  expect(layers()).toEqual(["blob:b:shown"]);
  expect(frame("b")).toBe(loadingFrame);
});

test("moving quickly only loads the last choice, with the same document on screen until then", () => {
  const view = render(<DocumentPreview {...pdf("a")}/>);
  fireEvent.load(frame("a")); pass(200); pass(120);
  view.rerender(<DocumentPreview {...pdf("b")}/>);
  fireEvent.load(frame("b")); pass(100);
  view.rerender(<DocumentPreview {...pdf("c")}/>);
  expect(layers()).toEqual(["blob:a:shown", "blob:c:loading"]);
  pass(5000 - 1);
  expect(layers()).toEqual(["blob:a:shown", "blob:c:loading"]);
  fireEvent.load(frame("c")); pass(200);
  expect(layers()).toEqual(["blob:a:leaving", "blob:c:shown"]);
});

test("a document that never reports loaded is still shown in the end", () => {
  render(<DocumentPreview {...pdf("a")}/>);
  pass(4999);
  expect(layers()).toEqual(["cover:shown", "blob:a:loading"]);
  pass(1);
  expect(layers()).toEqual(["cover:leaving", "blob:a:shown"]);
});

test("an image replaces the document as soon as it has loaded, or failed", () => {
  const view = render(<DocumentPreview url="blob:a" isPDF={false}/>);
  fireEvent.load(document.querySelector(".image-view img")); pass(0);
  expect(layers()).toEqual(["cover:leaving", "blob:a:shown"]);
  pass(120);
  view.rerender(<DocumentPreview url="blob:b" isPDF={false}/>);
  fireEvent.error(document.querySelectorAll(".image-view img")[1]); pass(0);
  expect(layers()).toEqual(["blob:a:leaving", "blob:b:shown"]);
});

test("the same document keeps its layer when only its details change", () => {
  const view = render(<DocumentPreview {...pdf("a")}/>);
  fireEvent.load(frame("a")); pass(200); pass(120);
  view.rerender(<DocumentPreview url="blob:a" isPDF={false}/>);
  expect(layers()).toEqual(["blob:a:shown"]);
  expect(frame("a")).toBeTruthy();
});

test("a switch that takes long dims the document still on screen and says the new one is opening", () => {
  const view = render(<DocumentPreview {...pdf("a")}/>);
  fireEvent.load(frame("a")); pass(200); pass(120);
  const stage = document.querySelector(".preview-stage");
  view.rerender(<DocumentPreview {...pdf("b")}/>);
  pass(399);
  expect(stage.classList.contains("waiting")).toBe(false);
  expect(document.querySelector(".preview-wait")).toBeNull();
  // Another switch in between does not restart the wait: the first document is still not the chosen one.
  view.rerender(<DocumentPreview {...pdf("c")}/>);
  pass(1);
  expect(stage.classList.contains("waiting")).toBe(true);
  expect(document.querySelector(".preview-wait").textContent).toBe("Đang mở bản xem trước…");
  expect(layers()).toEqual(["blob:a:shown", "blob:c:loading"]);
  fireEvent.load(frame("c")); pass(200);
  expect(layers()).toEqual(["blob:a:leaving", "blob:c:shown"]);
  expect(stage.classList.contains("waiting")).toBe(false);
  expect(document.querySelector(".preview-wait")).toBeNull();
});

test("a quick switch shows no waiting label", () => {
  const view = render(<DocumentPreview {...pdf("a")}/>);
  fireEvent.load(frame("a")); pass(200); pass(120);
  view.rerender(<DocumentPreview {...pdf("b")}/>);
  fireEvent.load(frame("b")); pass(200);
  expect(layers()).toEqual(["blob:a:leaving", "blob:b:shown"]);
  pass(400);
  expect(document.querySelector(".preview-stage").classList.contains("waiting")).toBe(false);
  expect(document.querySelector(".preview-wait")).toBeNull();
});

test("only the visible layer can be used; a loading bar exists while one is loading", () => {
  const view = render(<DocumentPreview {...pdf("a")}/>);
  expect(document.querySelector(".preview-loading")).toBeTruthy();
  fireEvent.load(frame("a")); pass(200); pass(120);
  expect(document.querySelector(".preview-loading")).toBeNull();
  view.rerender(<DocumentPreview {...pdf("b")}/>);
  expect(frame("a").closest(".preview-layer").hasAttribute("inert")).toBe(false);
  expect(frame("b").closest(".preview-layer").hasAttribute("inert")).toBe(true);
});

test("bigger PDFs get more time to draw; images need none", () => {
  expect(paintDelay({isPDF:true, size:0})).toBe(200);
  expect(paintDelay({isPDF:true, size:10 * MB})).toBe(1100);
  expect(paintDelay({isPDF:false, size:10 * MB})).toBe(0);
});
