"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const disableForm = document.querySelector("[data-mfa-disable]");
  disableForm?.addEventListener("submit", (event) => {
    if (!window.confirm("Turn off two-factor authentication?")) {
      event.preventDefault();
    }
  });

  document.querySelector("[data-mfa-print]")?.addEventListener("click", () => {
    window.print();
  });
});
