// Picks an option of the app's dropdown (components/ui/select.jsx) the way a user does.
export async function pick(user, trigger, value) {
  await user.click(trigger);
  await user.click(document.querySelector(`[role=option][data-value="${value}"]`));
}
