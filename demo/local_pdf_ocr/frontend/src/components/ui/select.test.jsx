// @vitest-environment jsdom
import React, {useState} from "react";
import {expect, test, vi} from "vitest";
import {render, screen} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Select from "./select.jsx";

const OPTIONS = [{value:"01",label:"01 · Vĩnh viễn"},{value:"02",label:"02 · 75 năm"},{value:"03",label:"03 · Đỏ tươi"},{value:"04",label:"04 · Tiếng Việt"}];

function setup({initial = "", ...props} = {}) {
  const onChange = vi.fn();
  function Host() {
    const [value, setValue] = useState(initial);
    return <><Select ariaLabel="Thử" options={OPTIONS} value={value} onChange={next => {onChange(next); setValue(next);}} {...props}/><button>Khác</button></>;
  }
  render(<Host/>);
  return {user:userEvent.setup(), onChange, trigger:screen.getByRole("combobox", {name:"Thử"})};
}
const listed = () => screen.queryAllByRole("option").map(option => option.textContent);
const activeOption = () => document.querySelector(".select-option.active")?.dataset.value;

test("its options exist only while it is open; a click picks one and returns to the trigger", async () => {
  const {user, trigger, onChange} = setup({initial:"02"});
  expect(listed()).toEqual([]);
  expect(trigger.textContent).toBe("02 · 75 năm");
  expect(trigger.value).toBe("02");
  await user.click(trigger);
  expect(trigger.getAttribute("aria-expanded")).toBe("true");
  expect(listed()).toEqual(["01 · Vĩnh viễn", "02 · 75 năm", "03 · Đỏ tươi", "04 · Tiếng Việt"]);
  expect(screen.getByRole("option", {selected:true}).dataset.value).toBe("02");
  await user.click(screen.getByRole("option", {name:"04 · Tiếng Việt"}));
  expect(onChange).toHaveBeenCalledWith("04");
  expect(listed()).toEqual([]);
  expect(trigger.textContent).toBe("04 · Tiếng Việt");
  expect(document.activeElement).toBe(trigger);
});

test("picking the current option changes nothing", async () => {
  const {user, trigger, onChange} = setup({initial:"02"});
  await user.click(trigger);
  await user.click(screen.getByRole("option", {name:"02 · 75 năm"}));
  expect(onChange).not.toHaveBeenCalled();
  expect(listed()).toEqual([]);
});

test("it works from the keyboard alone", async () => {
  const {user, trigger, onChange} = setup({initial:"02"});
  trigger.focus();
  await user.keyboard("{ArrowDown}");
  expect(activeOption()).toBe("02");
  expect(trigger.getAttribute("aria-activedescendant")).toBe(document.querySelector(".select-option.active").id);
  await user.keyboard("{ArrowDown}");
  expect(activeOption()).toBe("03");
  await user.keyboard("{End}{ArrowDown}");
  expect(activeOption()).toBe("04");
  await user.keyboard("{Home}{ArrowUp}");
  expect(activeOption()).toBe("01");
  await user.keyboard("{Escape}");
  expect(listed()).toEqual([]);
  expect(onChange).not.toHaveBeenCalled();
  await user.keyboard("{Enter}{ArrowDown}{Enter}");
  expect(onChange).toHaveBeenCalledWith("03");
});

test("typing jumps to a word, with or without accents", async () => {
  const {user, trigger, onChange} = setup();
  trigger.focus();
  await user.keyboard("do");
  expect(activeOption()).toBe("03");
  await user.keyboard("{Escape}");
  await new Promise(resolve => setTimeout(resolve, 650));
  await user.keyboard("{ArrowDown}");
  await user.keyboard("tieng v");
  expect(activeOption()).toBe("04");
  await user.keyboard("{Enter}");
  expect(onChange).toHaveBeenCalledWith("04");
});

test("clicking elsewhere closes it without a change; a disabled one does not open", async () => {
  const {user, trigger, onChange} = setup();
  await user.click(trigger);
  await user.click(screen.getByRole("button", {name:"Khác"}));
  expect(listed()).toEqual([]);
  expect(onChange).not.toHaveBeenCalled();
  await user.click(trigger);
  await user.click(trigger);
  expect(listed()).toEqual([]);
  document.body.innerHTML = "";
  const disabled = setup({disabled:true});
  await disabled.user.click(disabled.trigger);
  expect(listed()).toEqual([]);
});

test("moving the page closes it, but scrolling inside its own list does not", async () => {
  const {user, trigger} = setup();
  await user.click(trigger);
  document.querySelector(".select-content").dispatchEvent(new Event("scroll"));
  expect(listed()).toHaveLength(4);
  const {act} = await import("@testing-library/react");
  act(() => {document.body.dispatchEvent(new Event("scroll"));});
  expect(listed()).toEqual([]);
});

test("a placeholder shows when nothing is chosen; a code outside the list is still shown, not hidden", () => {
  const empty = setup({placeholder:"Chọn…"});
  expect(empty.trigger.textContent).toBe("Chọn…");
  expect(empty.trigger.querySelector(".select-value").className).toContain("placeholder");
  document.body.innerHTML = "";
  const unknown = setup({initial:"99"});
  expect(unknown.trigger.textContent).toBe("99");
  expect(unknown.trigger.querySelector(".select-value").className).not.toContain("placeholder");
});

test("it opens upward when there is no room below, and stays inside the window", async () => {
  const {user, trigger} = setup({popupMinWidth:300});
  trigger.getBoundingClientRect = () => ({top:700, bottom:730, left:900, right:990, width:90, height:30});
  Object.defineProperty(window, "innerHeight", {configurable:true, value:760});
  Object.defineProperty(window, "innerWidth", {configurable:true, value:1000});
  await user.click(trigger);
  const style = document.querySelector(".select-content").style;
  expect(style.bottom).toBe("64px");
  expect(style.top).toBe("");
  expect(style.width).toBe("300px");
  expect(style.left).toBe("692px");
  expect(style.maxHeight).toBe("320px");
});

test("prefixes share the widest one's width, and every option keeps a slot for the tick", async () => {
  const options = Array.from({length:12}, (_, i) => ({value:String(i), prefix:`File ${i + 1}/12`, label:`${i}.pdf`, hint:"Chưa xử lý"}));
  render(<Select ariaLabel="Tệp" options={options} value="0" onChange={() => {}}/>);
  const trigger = screen.getByRole("combobox", {name:"Tệp"});
  expect(trigger.querySelector(".select-prefix").dataset.widest).toBe("File 10/12");
  expect(trigger.textContent).toBe("File 1/120.pdfChưa xử lý");
  await userEvent.setup().click(trigger);
  const rows = screen.getAllByRole("option");
  expect(rows.map(row => row.querySelector(".select-prefix").dataset.widest)).toEqual(Array(12).fill("File 10/12"));
  expect(rows.map(row => row.querySelectorAll(".select-check").length)).toEqual(Array(12).fill(1));
  expect(rows.map(row => !!row.querySelector(".select-check svg"))).toEqual([true, ...Array(11).fill(false)]);
});
