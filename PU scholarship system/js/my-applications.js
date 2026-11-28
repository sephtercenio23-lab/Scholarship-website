let currentUser = null;
let applications = [];

runPage(startPage);

async function startPage() {
  currentUser = await requireRole(["student"]);
  if (!currentUser) return;
  initSidebar(currentUser, "applications");
  applications = await getApplicationsForStudent(currentUser.id);
  await initStudentFilters();
  showApplications();
  el("searchBox").addEventListener("input", showApplications);
  el("statusFilter").addEventListener("change", showApplications);
  el("applicationRows").addEventListener("click", (e) => {
    const button = e.target.closest("[data-open-app]");
    if (button) openDetails(button.dataset.openApp);
  });
  window.addEventListener("notification-arrived", () =>
    runPage(async () => {
      applications = await getApplicationsForStudent(currentUser.id);
      showApplications();
    })
  );
  const requested = getQueryParam("view");
  if (requested) openDetails(requested);
}

function showApplications() {
  const search = el("searchBox").value.trim().toLowerCase();
  const status = el("statusFilter").value;
  const shown = sortApplications(applications).filter((app) => {
    if (val("studentYear") && applicationYear(app) !== val("studentYear")) return false;
    if (val("studentTerm") && applicationTrimester(app) !== val("studentTerm")) return false;
    if (val("studentType") && app.scholarshipType !== val("studentType")) return false;
    if (val("studentPastDiscount") && String(app.pastDiscount ?? "") !== val("studentPastDiscount")) return false;
    const matchesSearch = [
      app.code,
      app.studentName,
      app.scholarshipType,
      app.term,
      app.program,
      app.academicYear,
      formatDate(app.dateSubmitted),
      app.discountPercent !== null && app.discountPercent !== undefined ? app.discountPercent + "%" : "",
      pastDiscountLabel(app.pastDiscount, true),
      app.status,
    ]
      .join(" ")
      .toLowerCase()
      .includes(search);
    const matchesStatus = !status || app.status === status;
    return matchesSearch && matchesStatus;
  });
  el("applicationRows").innerHTML = shown
    .map(
      (app) => `
    <tr>
      <td data-label="Application"><div><strong>${app.code}</strong><small>${escapeHtml(app.studentName)}</small></div></td>
      <td data-label="Scholarship">${app.scholarshipType}</td>
      <td data-label="Term">${termTag(app)}</td>
      <td data-label="Submitted">${formatDate(app.dateSubmitted)}</td>
      <td data-label="Discount %">${app.discountPercent !== null && app.discountPercent !== undefined ? escapeHtml(app.discountPercent) + "%" : "&mdash;"}</td>
      <td data-label="Status">${statusBadge(app.status)}</td>
      <td data-label=""><button type="button" class="text-link" data-open-app="${app.id}">Details <i class="ti ti-arrow-right"></i></button>${whatsNextHtml(app)}</td>
    </tr>`
    )
    .join("");
  el("studentFilterCount").textContent = `Showing ${shown.length} of ${applications.length} applications`;
  el("emptyState").classList.toggle("hidden", shown.length > 0);
}

function openDetails(appId) {
  const app = applications.find((item) => item.id === appId);
  if (!app) return;
  let resultHtml = "";
  if (app.status === "Approved" || app.status === "Rejected") {
    const isApproved = app.status === "Approved";
    const fallback = isApproved ? "Your application has been approved." : "Your application was not approved.";
    resultHtml = `
      <h3 class="modal-subhead">Evaluation result</h3>
      <div class="alert ${isApproved ? "alert-success" : "alert-error"} show">${escapeHtml(app.remarks) || fallback}</div>`;
  }
  el("detailBody").innerHTML =
    applicationDetailsHtml(app) +
    resultHtml +
    `
    <p class="modal-text modal-text-spaced">${
      app.archived
        ? `This application was submitted in ${escapeHtml(app.term)}, which has ended. ` +
          `It is kept here as your record - the details, documents and result stay exactly as they were. ` +
          `To apply for this term, submit a new application from the Scholarships page.`
        : "The CSS Office reviews your requirements. Check your application details for updates and results."
    }</p>`;
  openModal("detailModal");
}
function applicationYear(app) {
  return app.academicYear || (app.term || "").match(/\d{4}[–-]\d{4}/)?.[0] || "";
}

function applicationTrimester(app) {
  return app.trimester || (app.term || "").split(/,| · /)[0] || "";
}

async function initStudentFilters() {
  const toolbar = document.querySelector(".table-toolbar");
  const controls = [
    ["studentYear", "Academic year", [...new Set(applications.map(applicationYear).filter(Boolean))].sort().reverse()],
    ["studentTerm", "Term", TRIMESTERS],
    ["studentType", "Scholarship type", SCHOLARSHIP_TYPES],
    ["studentPastDiscount", "Past discount", PAST_DISCOUNT_OPTIONS.map((option) => ({ value: option.value, label: option.value === "none" ? "Not a scholar" : option.label }))],
  ];
  controls.forEach(([id, label, options]) => {
    const optionsHtml = options
      .map((option) => {
        const value = typeof option === "string" ? option : option.value;
        const text = typeof option === "string" ? option : option.label;
        return `<option value="${escapeHtml(value)}">${escapeHtml(text)}</option>`;
      })
      .join("");
    toolbar.insertAdjacentHTML("beforeend", `<select class="plain-select" id="${id}" aria-label="${label}"><option value="">${label}: All</option>${optionsHtml}</select>`);
    el(id).addEventListener("change", showApplications);
  });
  toolbar.insertAdjacentHTML("beforeend", '<button type="button" class="btn btn-outline btn-sm" id="studentClearFilters">Clear filters</button>');
  toolbar.insertAdjacentHTML("afterend", '<p class="filter-count" id="studentFilterCount" aria-live="polite"></p>');
  el("studentClearFilters").addEventListener("click", () => {
    ["studentYear", "studentTerm", "studentType", "studentPastDiscount", "statusFilter", "searchBox"].forEach((id) => { el(id).value = ""; });
    showApplications();
  });
}

function nextDocumentRowHtml(app, requirement) {
  const info = app.postApprovalDocuments?.[requirement.key];
  if (!info) {
    return `
      <div class="compact-doc-row">
        <span class="compact-doc-name"><i class="ti ti-circle-dashed"></i> ${requirement.label}</span>
        <span class="compact-doc-foot">
          <span class="compact-doc-state">Not uploaded yet</span>
          ${app.archived ? "" : `<button type="button" class="text-link" data-upload-doc="${app.id}" data-doc-key="${requirement.key}">Upload</button>`}
        </span>
      </div>`;
  }
  const accepted = info.reviewStatus === "Valid";
  const rejected = info.reviewStatus === "Rejected";
  const stateClass = accepted ? "state-accepted" : rejected ? "state-rejected" : "state-pending";
  const stateText = accepted
    ? `Accepted &middot; attempt ${info.attemptNo} of ${info.maxAttempts}`
    : rejected
      ? info.attemptNo < info.maxAttempts
        ? `Rejected &middot; attempt ${info.attemptNo} of ${info.maxAttempts}`
        : "Rejected &middot; no attempts left"
      : `Under review &middot; attempt ${info.attemptNo} of ${info.maxAttempts}`;
  const icon = accepted ? "ti-circle-check" : rejected ? "ti-circle-x" : "ti-hourglass";
  const resubmit = rejected && info.attemptNo < info.maxAttempts && !app.archived;
  return `
      <div class="compact-doc-row">
        <span class="compact-doc-name"><i class="ti ${icon}"></i> ${requirement.label}</span>
        <span class="compact-doc-foot">
          <span class="compact-doc-state ${stateClass}">${stateText}</span>
          <button type="button" class="text-link" data-file-app="${app.id}" data-file-key="${requirement.key}">View</button>
          ${resubmit ? `<button type="button" class="text-link" data-upload-doc="${app.id}" data-doc-key="${requirement.key}">Resubmit</button>` : ""}
        </span>
      </div>`;
}

function whatsNextHtml(app) {
  if (app.status !== "Approved") return "";
  return `
      <div class="post-approval-compact">
        <p class="compact-section-label">What's next</p>
        ${POST_APPROVAL_SCHOLARSHIP_REQUIREMENTS.map((requirement) => nextDocumentRowHtml(app, requirement)).join("")}
      </div>`;
}
