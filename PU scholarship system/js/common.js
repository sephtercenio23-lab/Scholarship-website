function el(id) {
  return document.getElementById(id);
}

function val(id) {
  return el(id).value.trim();
}

const HTML_ESCAPES = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

function escapeHtml(text) {
  if (!text) return "";
  return String(text).replace(/[&<>"']/g, (c) => HTML_ESCAPES[c]);
}
function getInitials(name) {
  if (!name) return "?";
  const parts = name.trim().split(" ");
  return (parts[0][0] + (parts[1] ? parts[1][0] : "")).toUpperCase();
}
function formatDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
function formatDateTime(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
function localDateStr(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function statusBadgeClass(status) {
  return "badge-" + status.toLowerCase().replace(/\s+/g, "-");
}
function statusBadge(status) {
  return `<span class="badge ${statusBadgeClass(status)}">${status}</span>`;
}
function showAlert(id, message) {
  const box = el(id);
  box.textContent = message;
  box.classList.add("show");
}
function hideAlert(id) {
  const box = el(id);
  if (box) box.classList.remove("show");
}
function showToast(message, isError) {
  let toast = el("appToast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "appToast";
    toast.className = "toast";
    toast.innerHTML = `
      <i class="ti ti-circle-check"></i>
      <span id="appToastText"></span>
      <button type="button" class="toast-close" id="appToastClose" aria-label="Close message"><i class="ti ti-x"></i></button>`;
    document.body.appendChild(toast);
    el("appToastClose").addEventListener("click", () => toast.classList.remove("show"));
  }
  toast.classList.toggle("toast-error", !!isError);
  toast.querySelector("i").className = isError ? "ti ti-alert-circle" : "ti ti-circle-check";
  el("appToastText").textContent = message;
  toast.classList.add("show");
  clearTimeout(toast.hideTimer);
  toast.hideTimer = setTimeout(() => toast.classList.remove("show"), 4000);
}
function setFlash(message) {
  sessionStorage.setItem("sams_flash", message);
}
function showFlashIfAny() {
  const message = sessionStorage.getItem("sams_flash");
  if (!message) return;
  sessionStorage.removeItem("sams_flash");
  showToast(message);
}
function openModal(id) {
  el(id).classList.add("show");
  document.body.classList.add("modal-open");
}
function closeModal(id) {
  el(id).classList.remove("show");
  if (!document.querySelector(".modal-overlay.show")) document.body.classList.remove("modal-open");
}
function closeAllModals() {
  document.querySelectorAll(".modal-overlay.show").forEach((box) => closeModal(box.id));
}
document.addEventListener("click", (e) => {
  const closeButton = e.target.closest("[data-close-modal]");
  if (closeButton) {
    closeModal(closeButton.closest(".modal-overlay").id);
    return;
  }
  if (e.target.classList.contains("modal-overlay")) closeModal(e.target.id);
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeAllModals();
});
function homePageFor(user) {
  return user.role === "student" ? "student-dashboard.html" : "staff-dashboard.html";
}
async function requireRole(allowedRoles) {
  const user = await getCurrentUser();
  if (!user) {
    window.location.href = "index.html";
    return null;
  }
  if (allowedRoles && !allowedRoles.includes(user.role)) {
    window.location.href = homePageFor(user);
    return null;
  }
  return user;
}
async function redirectIfLoggedIn() {
  const user = await getCurrentUser();
  if (!user) return false;
  window.location.href = homePageFor(user);
  return true;
}
async function logout() {
  await signOutUser();
  window.location.href = "index.html";
}
let pageIsLeaving = false;
window.addEventListener("pagehide", () => {
  pageIsLeaving = true;
});
function runPage(work) {
  return work().catch((error) => {
    if (pageIsLeaving) return;
    console.error(error);
    showToast(friendlyError(error), true);
  });
}
function newId() {
  if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}
function getQueryParam(name) {
  return new URLSearchParams(window.location.search).get(name);
}
showFlashIfAny();
function applicationTermLabel(app) {
  return app.term ? app.term.replace(/, AY /g, " · AY ") : "—";
}

function termTag(app) {
  return `<span class="term-tag ${app.archived ? "term-past" : ""}"><i class="ti ti-calendar-event"></i> ${escapeHtml(applicationTermLabel(app))}</span>${app.archived ? ' <small class="term-tag-note">Past term</small>' : ""}`;
}

function dutyKey(app) {
  return app.dutyCompleted || Number(app.dutyHours || 0) === 80 ? "Completed the 80 Hours" : Number(app.dutyHours || 0) > 0 ? "In Progress" : "Not Started";
}

function reportState(app) {
  return app.reportReceivedAt || (app.documents && app.documents.terminalReport) ? "Submitted" : "Not Yet Available";
}

function sortApplications(apps) {
  return [...apps].sort((a, b) => {
    const key = (app) => `${app.academicYear || (app.term || "").match(/\d{4}[–-]\d{4}/)?.[0] || ""}${app.trimester || app.term || ""}${app.dateSubmitted || ""}`;
    return key(b).localeCompare(key(a));
  });
}

let viewingTerms = [];
let viewingYear = "";
let viewingTerm = "";

function selectedViewingTerm() {
  return viewingTerms.find((term) => term.id === viewingTerm) || null;
}

function matchesViewing(app) {
  if (!viewingYear && !viewingTerm) return true;
  const term = viewingTerms.find((item) => item.id === app.termId || item.label === app.term);
  return !!term && (!viewingYear || term.academicYear === viewingYear) && (!viewingTerm || term.id === viewingTerm);
}

function syncViewingAddress() {
  const url = new URL(window.location.href);
  url.searchParams.set("year", viewingYear || "all");
  url.searchParams.set("term", viewingTerm || "all");
  history.replaceState(null, "", url);
  document.querySelectorAll('a[href*="staff-dashboard.html"], a[href*="staff-applications.html"]').forEach((link) => {
    const target = new URL(link.href);
    target.searchParams.set("year", viewingYear || "all");
    target.searchParams.set("term", viewingTerm || "all");
    link.href = target.href;
  });
}

async function initViewing(container, allowAll, onChange) {
  viewingTerms = await getAcademicTerms();
  const current = viewingTerms.find((term) => term.state === "Current");
  const requestedTerm = viewingTerms.find((term) => term.id === getQueryParam("term"));
  viewingYear = getQueryParam("year") === "all" ? (allowAll ? "" : requestedTerm?.academicYear || current.academicYear) : getQueryParam("year") || current.academicYear;
  if (!viewingTerms.some((term) => term.academicYear === viewingYear) && viewingYear) viewingYear = current.academicYear;
  viewingTerm = getQueryParam("term") === "all" && allowAll ? "" : getQueryParam("term") || current.id;
  if (!viewingTerms.some((term) => term.id === viewingTerm && (!viewingYear || term.academicYear === viewingYear)) && viewingTerm) {
    viewingTerm = viewingTerms.find((term) => term.academicYear === viewingYear)?.id || current.id;
  }
  container.insertAdjacentHTML("beforeend", `
    <div class="viewing-row">
      <label class="viewing-label">Viewing <select class="plain-select" id="viewingYear" aria-label="Viewing academic year"></select></label>
      <select class="plain-select" id="viewingTerm" aria-label="Viewing term"></select>
    </div>`);
  const banner = document.createElement("div");
  banner.id = "viewingBanner";
  banner.className = "notice notice-spaced";
  container.insertAdjacentElement("afterend", banner);
  banner.insertAdjacentHTML("afterend", '<p class="term-tag-note" id="programTermNotice" hidden>Not offered for Nursing</p>');
  function render() {
    const years = [...new Set(viewingTerms.map((term) => term.academicYear))].sort().reverse();
    el("viewingYear").innerHTML = (allowAll ? '<option value="">All years</option>' : "") + years.map((year) => `<option value="${year}">AY ${year}</option>`).join("");
    el("viewingYear").value = viewingYear;
    el("viewingTerm").innerHTML = (allowAll ? '<option value="">All terms</option>' : "") + viewingTerms.filter((term) => !viewingYear || term.academicYear === viewingYear).map((term) => `<option value="${term.id}">${escapeHtml(term.trimester)}${!viewingYear ? " · AY " + term.academicYear : ""} · ${term.state}</option>`).join("");
    el("viewingTerm").value = viewingTerm;
    const term = selectedViewingTerm();
    banner.hidden = !term || term.state === "Current";
    el("programTermNotice").hidden = term?.trimester !== "3rd Trimester";
    banner.innerHTML = term ? `<span class="badge">${term.state === "Upcoming" ? "Upcoming term" : "Past term"}</span> Viewing ${escapeHtml(term.label.replace(", AY ", " · AY "))}${term.state === "Past" ? " (past term, read-only)" : ""}` : "";
    syncViewingAddress();
  }
  el("viewingYear").addEventListener("change", () => {
    viewingYear = val("viewingYear");
    viewingTerm = allowAll ? "" : viewingTerms.find((term) => term.academicYear === viewingYear).id;
    render();
    runPage(onChange);
  });
  el("viewingTerm").addEventListener("change", () => {
    viewingTerm = val("viewingTerm");
    render();
    runPage(onChange);
  });
  container.resetViewing = () => {
    viewingYear = current.academicYear;
    viewingTerm = current.id;
    render();
  };
  render();
}

function programOptions(saved) {
  const programs = [...new Set([...PROGRAMS.map((program) => program.name), ...(saved ? [saved] : [])])];
  return '<option value="">Select degree program</option>' + programs.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("");
}

function programNotOffered(program, trimester) {
  return trimester === "3rd Trimester" && (/nursing/i.test(program) || PROGRAMS.find((item) => item.name === program)?.terms === 2);
}

function manilaDateParts(iso) {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  const parts = {};
  new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Manila",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date).forEach((part) => {
    parts[part.type] = part.value;
  });
  return parts;
}

function manilaDateTimeLocal(iso) {
  const parts = manilaDateParts(iso);
  if (!parts) return "";
  const hour = parts.hour === "24" ? "00" : parts.hour;
  return `${parts.year}-${parts.month}-${parts.day}T${hour}:${parts.minute}`;
}

function sameManilaDay(iso, reference) {
  const a = manilaDateParts(iso);
  const b = manilaDateParts(reference);
  return a && b && a.year === b.year && a.month === b.month && a.day === b.day;
}

function scholarshipDeadlineInfo(scholarship) {
  if (!scholarship.deadlineAt) {
    return {
      closed: scholarship.effectiveStatus === "Closed",
      label: scholarship.effectiveStatus === "Closed" ? "Closed" : "",
      text: scholarship.deadline || DEADLINE_TEXT,
    };
  }
  const deadline = new Date(scholarship.deadlineAt);
  const diffMs = deadline.getTime() - Date.now();
  if (scholarship.effectiveStatus === "Closed" || diffMs <= 0) {
    return { closed: true, label: "Closed", text: scholarship.deadline || DEADLINE_TEXT };
  }
  if (sameManilaDay(scholarship.deadlineAt, new Date().toISOString())) {
    return { closed: false, label: "Closes today", text: scholarship.deadline || DEADLINE_TEXT };
  }
  const hours = Math.floor(diffMs / 3600000);
  if (hours < 24) {
    return { closed: false, label: `Closes in ${hours} hour${hours === 1 ? "" : "s"}`, text: scholarship.deadline || DEADLINE_TEXT };
  }
  const days = Math.ceil(diffMs / 86400000);
  return { closed: false, label: `Closes in ${days} day${days === 1 ? "" : "s"}`, text: scholarship.deadline || DEADLINE_TEXT };
}

function addPasswordToggle(input) {
  const wrap = input.closest(".input-wrap");
  if (!wrap || wrap.querySelector(".password-toggle")) return;
  wrap.classList.add("has-password-toggle");
  const button = document.createElement("button");
  button.type = "button";
  button.className = "password-toggle";
  button.setAttribute("aria-label", "Show password");
  button.innerHTML = '<i class="ti ti-eye"></i>';
  button.addEventListener("click", () => {
    const isHidden = input.type === "password";
    input.type = isHidden ? "text" : "password";
    button.setAttribute("aria-label", isHidden ? "Hide password" : "Show password");
    button.querySelector("i").className = isHidden ? "ti ti-eye-off" : "ti ti-eye";
  });
  wrap.appendChild(button);
}

function initPasswordToggles(root = document) {
  const scope = root || document;
  scope.querySelectorAll('.input-wrap input[type="password"]').forEach(addPasswordToggle);
}

initPasswordToggles(document);
new MutationObserver((mutations) => {
  mutations.forEach((mutation) => {
    mutation.addedNodes.forEach((node) => {
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      if (node.classList?.contains("input-wrap") || node.querySelector?.(".input-wrap")) {
        initPasswordToggles(node);
      }
    });
  });
}).observe(document.documentElement, { childList: true, subtree: true });
