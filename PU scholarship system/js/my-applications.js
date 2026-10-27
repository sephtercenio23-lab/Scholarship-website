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
    if (val("studentDuty") && (app.status !== "Approved" || (val("studentDuty") === "Complete" ? Number(app.dutyHours) !== 80 : !(Number(app.dutyHours) > 0 && Number(app.dutyHours) < 80)))) return false;
    const matchesSearch = [
      app.code,
      app.studentName,
      app.scholarshipType,
      app.term,
      app.program,
      app.academicYear,
      app.status === "Approved" ? dutyKey(app) : "",
      formatDate(app.dateSubmitted),
      app.discountPercent ? app.discountPercent + "%" : "",
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
      <td data-label="Discount %">${app.discountPercent ? escapeHtml(app.discountPercent) + "%" : "&mdash;"}</td>
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
        : "The CSS Office reviews your requirements. Check this history for updates and the release of results."
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
    ["studentDuty", "Duty", ["In progress", "Complete"]],
  ];
  controls.forEach(([id, label, options]) => {
    toolbar.insertAdjacentHTML("beforeend", `<select class="plain-select" id="${id}" aria-label="${label}"><option value="">${label}: All</option>${options.map((option) => `<option value="${escapeHtml(option)}">${escapeHtml(option)}</option>`).join("")}</select>`);
    el(id).addEventListener("change", showApplications);
  });
  toolbar.insertAdjacentHTML("beforeend", '<button type="button" class="btn btn-outline btn-sm" id="studentClearFilters">Clear filters</button>');
  toolbar.insertAdjacentHTML("afterend", '<p class="filter-count" id="studentFilterCount" aria-live="polite"></p>');
  el("studentClearFilters").addEventListener("click", () => {
    ["studentYear", "studentTerm", "studentType", "studentDuty", "statusFilter", "searchBox"].forEach((id) => { el(id).value = ""; });
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

function nextDutyRowHtml(app) {
  const complete = Boolean(app.dutyCompleted) || Number(app.dutyHours) === 80;
  const hours = complete ? 80 : Math.max(0, Math.min(79, Number(app.dutyHours || 0)));
  const stateClass = complete ? "state-accepted" : hours > 0 ? "state-pending" : "";
  const stateText = complete
    ? "Completed &middot; 80 of 80 hours"
    : hours > 0
      ? `In progress &middot; ${hours} of 80 hours`
      : "Not started &middot; 0 of 80 hours";
  const icon = complete ? "ti-circle-check" : "ti-circle-dashed";
  return `
      <div class="compact-doc-row">
        <span class="compact-doc-name"><i class="ti ${icon}"></i> Duty hours</span>
        <span class="compact-doc-foot"><span class="compact-doc-state ${stateClass}">${stateText}</span></span>
      </div>`;
}

function nextReportRowHtml(app) {
  const doc = app.documents?.terminalReport;
  const dutyComplete = Boolean(app.dutyCompleted) || Number(app.dutyHours) === 80;
  const received = Boolean(app.reportReceivedAt);
  const stateClass = received ? "state-accepted" : doc ? "state-pending" : "";
  const stateText = received
    ? `Received &middot; ${formatDate(app.reportReceivedAt)}`
    : doc
      ? `Submitted &middot; ${formatDate(doc.uploadedAt)}`
      : dutyComplete
        ? "Not submitted yet"
        : "After 80 duty hours";
  const icon = received ? "ti-circle-check" : doc ? "ti-hourglass" : "ti-circle-dashed";
  const action = !app.archived && dutyComplete && !received ? (doc ? "Replace" : "Submit") : "";
  return `
      <div class="compact-doc-row">
        <span class="compact-doc-name"><i class="ti ${icon}"></i> Terminal report</span>
        <span class="compact-doc-foot">
          <span class="compact-doc-state ${stateClass}">${stateText}</span>
          ${doc ? `<button type="button" class="text-link" data-file-app="${app.id}" data-file-key="terminalReport">View</button>` : ""}
          ${action ? `<button type="button" class="text-link" data-submit-report="${app.id}">${action}</button>` : ""}
        </span>
      </div>`;
}

function whatsNextHtml(app) {
  if (app.status !== "Approved") return "";
  return `
      <div class="post-approval-compact">
        <p class="compact-section-label">What's next</p>
        ${POST_APPROVAL_SCHOLARSHIP_REQUIREMENTS.map((requirement) => nextDocumentRowHtml(app, requirement)).join("")}
        ${nextDutyRowHtml(app)}
        ${nextReportRowHtml(app)}
      </div>`;
}
