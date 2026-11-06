import {clsx} from "clsx";
import {twMerge} from "tailwind-merge";

export function cn(...inputs) {
  return twMerge(clsx(inputs));
}
// Names are often typed without accents: "quyet dinh" finds "Quyết định".
export function searchKey(text) {
  return String(text ?? "").normalize("NFD").replace(/\p{M}/gu, "").replace(/đ/giu, "d").toLowerCase();
}
