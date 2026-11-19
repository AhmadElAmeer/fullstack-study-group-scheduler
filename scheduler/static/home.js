import { api } from "./api.js";

const form = document.getElementById("create");
const error = document.getElementById("create-error");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  error.textContent = "";
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    const group = await api("POST", "/api/groups", { name: form.elements.name.value });
    location.href = group.url;
  } catch (err) {
    error.textContent = err.message;
    button.disabled = false;
  }
});
