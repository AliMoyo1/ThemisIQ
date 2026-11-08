"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const password = document.getElementById("new_password");
  const fill = document.getElementById("strengthFill");
  const label = document.getElementById("strengthLabel");
  if (!password || !fill || !label) return;

  const checks = {
    len: value => value.length >= 8,
    upper: value => /[A-Z]/.test(value),
    lower: value => /[a-z]/.test(value),
    digit: value => /[0-9]/.test(value),
    special: value => /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>/?]/.test(value),
  };
  const levels = [
    { min: 0, label: "", color: "var(--border)", pct: 0 },
    { min: 1, label: "Weak", color: "#ef4444", pct: 20 },
    { min: 2, label: "Fair", color: "#f97316", pct: 40 },
    { min: 3, label: "Good", color: "#eab308", pct: 60 },
    { min: 4, label: "Strong", color: "#22c55e", pct: 80 },
    { min: 5, label: "Excellent", color: "#059669", pct: 100 },
  ];
  const rules = document.querySelectorAll(".pw-rule");

  function updateStrength() {
    const value = password.value;
    let score = 0;
    rules.forEach(element => {
      const check = checks[element.dataset.rule];
      if (!check) return;
      const passed = check(value);
      element.classList.toggle("pass", passed);
      element.classList.toggle("fail", !passed);
      if (passed) score += 1;
    });
    const level = levels.filter(item => score >= item.min).pop();
    fill.style.width = `${level.pct}%`;
    fill.style.background = level.color;
    label.textContent = value ? level.label : "";
    label.style.color = level.color;
  }

  password.addEventListener("input", updateStrength);
  updateStrength();
});
