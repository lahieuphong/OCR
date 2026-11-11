// @vitest-environment jsdom
import React from "react";
import {afterEach, expect, test, vi} from "vitest";
import {render, screen, waitFor, within} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AppMenu from "./AppMenu.jsx";

function fakeBridge({updates = true, check = {type:"info", message:"Bạn đang dùng bản mới nhất (0.1.1)."}} = {}) {
  let zoom = 100;
  const steps = [80, 90, 100, 110, 125];
  return {
    info: vi.fn(async () => ({version:"0.1.1", platform:"win32", updates, zoom})),
    openStatus: vi.fn(async () => true),
    openLogs: vi.fn(async () => true),
    checkUpdates: vi.fn(async () => check),
    zoom: vi.fn(async step => {
      zoom = step === 0 ? 100 : step > 0 ? steps.find(value => value > zoom) ?? zoom : [...steps].reverse().find(value => value < zoom) ?? zoom;
      return zoom;
    }),
    quit: vi.fn(async () => null),
  };
}
afterEach(() => {delete window.vietdocDesktop;});

test("a browser has no desktop bridge, so no app menu is drawn", async () => {
  render(<AppMenu/>);
  await new Promise(resolve => setTimeout(resolve, 0));
  expect(screen.queryByRole("button", {name:"Menu ứng dụng"})).toBeNull();
});

test("the menu lists the app actions, runs them and closes; the display size stays open and changes", async () => {
  const bridge = fakeBridge(), user = userEvent.setup();
  window.vietdocDesktop = bridge;
  render(<AppMenu/>);
  const trigger = await screen.findByRole("button", {name:"Menu ứng dụng"});
  expect(trigger.getAttribute("aria-haspopup")).toBe("menu");
  await user.click(trigger);
  const menu = screen.getByRole("menu", {name:"Menu ứng dụng"});
  expect(trigger.getAttribute("aria-expanded")).toBe("true");
  expect(menu.textContent).toContain("Phiên bản 0.1.1");
  expect(within(menu).getAllByRole("menuitem").map(item => item.getAttribute("aria-label") || item.querySelector(".app-menu-text span")?.textContent))
    .toEqual(["Trạng thái hệ thống", "Mở thư mục nhật ký", "Kiểm tra cập nhật", "Thu nhỏ", "Cỡ hiển thị 100%, bấm để về 100%", "Phóng to", "Thoát VietDoc OCR"]);
  expect(document.activeElement.textContent).toContain("Trạng thái hệ thống");
  await user.click(within(menu).getByRole("menuitem", {name:"Phóng to"}));
  window.dispatchEvent(new Event("resize"));   // a new display size resizes the page: the menu stays open
  await user.click(within(screen.getByRole("menu")).getByRole("menuitem", {name:"Phóng to"}));
  expect(within(menu).getByRole("menuitem", {name:/^Cỡ hiển thị 125%/}).textContent).toBe("125%");
  await user.click(within(menu).getByRole("menuitem", {name:/^Cỡ hiển thị/}));
  expect(bridge.zoom.mock.calls.map(([step]) => step)).toEqual([1, 1, 0]);
  expect(within(menu).getByRole("menuitem", {name:/^Cỡ hiển thị/}).textContent).toBe("100%");
  await user.click(within(menu).getByRole("menuitem", {name:/Trạng thái hệ thống/}));
  expect(bridge.openStatus).toHaveBeenCalledOnce();
  expect(screen.queryByRole("menu")).toBeNull();
  await user.click(trigger); await user.click(screen.getByRole("menuitem", {name:/Mở thư mục nhật ký/}));
  await user.click(trigger); await user.click(screen.getByRole("menuitem", {name:/Thoát VietDoc OCR/}));
  expect([bridge.openLogs.mock.calls.length, bridge.quit.mock.calls.length]).toEqual([1, 1]);
});

test("arrows move through the items, Escape closes and gives focus back, a click outside closes", async () => {
  window.vietdocDesktop = fakeBridge({updates:false});
  const user = userEvent.setup();
  render(<><AppMenu/><p>ngoài menu</p></>);
  const trigger = await screen.findByRole("button", {name:"Menu ứng dụng"});
  trigger.focus(); await user.keyboard("{ArrowDown}");
  const menu = screen.getByRole("menu");
  expect(within(menu).queryByRole("menuitem", {name:/Kiểm tra cập nhật/})).toBeNull();   // a copy that does not update itself
  expect(document.activeElement.textContent).toContain("Trạng thái hệ thống");
  await user.keyboard("{ArrowDown}"); expect(document.activeElement.textContent).toContain("Mở thư mục nhật ký");
  await user.keyboard("{End}"); expect(document.activeElement.textContent).toContain("Thoát VietDoc OCR");
  await user.keyboard("{ArrowDown}"); expect(document.activeElement.textContent).toContain("Trạng thái hệ thống");
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("menu")).toBeNull(); expect(document.activeElement).toBe(trigger);
  await user.click(trigger); await user.click(screen.getByText("ngoài menu"));
  expect(screen.queryByRole("menu")).toBeNull();
});

test("checking for updates shows the answer in the app's own dialog, a failure as a warning", async () => {
  let answer;
  const bridge = fakeBridge();
  bridge.checkUpdates = vi.fn(() => new Promise(resolve => {answer = resolve;}));
  window.vietdocDesktop = bridge;
  const user = userEvent.setup();
  render(<AppMenu/>);
  await user.click(await screen.findByRole("button", {name:"Menu ứng dụng"}));
  await user.click(screen.getByRole("menuitem", {name:/Kiểm tra cập nhật/}));
  const dialog = document.querySelector("dialog.update-dialog");
  expect(dialog.textContent).toContain("Đang kiểm tra bản mới trên GitHub");
  expect(within(dialog).getByRole("button", {name:"Đóng"}).disabled).toBe(true);
  answer({type:"info", message:"Đang tải VietDoc OCR 0.1.2. Bản mới được cài khi bạn đóng ứng dụng."});
  await waitFor(() => expect(dialog.textContent).toContain("Đang tải VietDoc OCR 0.1.2"));
  await user.click(within(dialog).getByRole("button", {name:"Đóng"}));
  expect(document.querySelector("dialog.update-dialog")).toBeNull();
  bridge.checkUpdates = vi.fn(async () => ({type:"warning", message:"Không kiểm tra được bản cập nhật. Cần kết nối Internet tới GitHub.", detail:"net::ERR_INTERNET_DISCONNECTED"}));
  await user.click(screen.getByRole("button", {name:"Menu ứng dụng"}));
  await user.click(screen.getByRole("menuitem", {name:/Kiểm tra cập nhật/}));
  await waitFor(() => expect(document.querySelector(".update-message.warning")).not.toBeNull());
  expect(document.querySelector(".update-detail").textContent).toBe("net::ERR_INTERNET_DISCONNECTED");
});
