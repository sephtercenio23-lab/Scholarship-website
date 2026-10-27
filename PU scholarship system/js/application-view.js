function applicationDetailsHtml(app, editable) {
  const discountEditable = editable && app.status === "Approved" && !app.archived;
  const gradeRemarks = [
    app.hasFailingGrade ? "Failing grade" : "",
    app.hasIncompleteGrade ? "INC" : "",
    app.hasDroppedGrade ? "Dropped" : "",
  ].filter(Boolean);
  const documentsHtml = [...INITIAL_SCHOLARSHIP_REQUIREMENTS, ...(app.documents.terminalReport ? [{ key: "terminalReport", label: "Terminal report" }] : [])].map((requirement) => {
    const doc = app.documents[requirement.key];
    if (doc && doc.name) {
      return `
        <button type="button" class="document-preview" data-file-app="${app.id}" data-file-key="${requirement.key}" title="Click to view this file">
          <i class="ti ti-file-text"></i>
          <span>${requirement.label}<small>${escapeHtml(doc.name)}${requirement.key === "terminalReport" ? " · " + formatDate(doc.uploadedAt) + " · " + (app.reportReceivedAt ? "Received" : "Submitted") : ""}</small></span>
          <i class="ti ti-eye view-icon"></i>
        </button>`;
    }
    return `
      <div class="document-preview document-missing">
        <i class="ti ti-file-off"></i>
        <span>${requirement.label}<small>Not submitted</small></span>
      </div>`;
  }).join("");
  const historyHtml = app.history
    .map(
      (entry) => `
    <li>
      <strong>${entry.status}</strong>
      <small>${formatDateTime(entry.date)}${entry.by ? " &middot; " + escapeHtml(entry.by) : ""}</small>
      ${entry.remarks ? `<p>${escapeHtml(entry.remarks)}</p>` : ""}
    </li>`
    )
    .join("");
  const termHtml = app.term
    ? `
    <div class="term-tag-row">
      <span class="term-tag ${app.archived ? "term-past" : ""}">
        <i class="ti ti-calendar-event"></i> ${escapeHtml(applicationTermLabel(app))}
      </span>
      ${app.archived ? '<span class="term-tag-note">Past term &middot; kept for records, no longer being evaluated</span>' : ""}
    </div>`
    : termTag(app);
  return `
    ${termHtml}
    <div class="detail-banner">
      <div>
        <span class="micro">${app.code}</span>
        <h3>${app.scholarshipType}</h3>
      </div>
      ${statusBadge(app.status)}
    </div>

    <dl class="detail-list">
      <dt>Student</dt><dd>${escapeHtml(app.studentName)} (${escapeHtml(app.studentId)})</dd>
      <dt>Email</dt><dd>${escapeHtml(app.universityEmail)}</dd>
      <dt>Program / year</dt><dd>${escapeHtml(app.program)} &middot; ${escapeHtml(app.yearLevel)}</dd>
      <dt>GWA</dt><dd>${app.gwa ? escapeHtml(app.gwa) : "\u2014"}</dd>
      <dt>Lowest grade</dt><dd>${app.lowestGrade ? escapeHtml(app.lowestGrade) : "\u2014"}</dd>
      <dt>Grade remarks</dt><dd>${gradeRemarks.length ? escapeHtml(gradeRemarks.join(", ")) : "No failing grade, INC, or dropped remarks declared"}</dd>
      <dt>Term</dt><dd>${escapeHtml(app.term || "\u2014")}</dd>
      <dt>Submitted</dt><dd>${formatDate(app.dateSubmitted)}</dd>
      <dt>Tuition fee discount</dt><dd data-discount-cell><span class="discount-value">${app.discountPercent ? escapeHtml(app.discountPercent) + "%" : "\u2014"}</span>${discountEditable ? ' <button type="button" class="icon-btn" data-discount-action="edit" title="Edit discount"><i class="ti ti-pencil"></i></button>' : ""}</dd>
      ${app.status === "Approved" ? `<dt>Duty rendered</dt><dd data-duty-cell>${dutyDetailsHtml(app)}</dd>` : ""}
    </dl>

    <h3 class="modal-subhead">Submitted requirements</h3>
    <div class="submitted-documents">${documentsHtml}</div>
    ${app.documents.terminalReport ? `<p><span class="badge">${app.reportReceivedAt ? "Received" : "Submitted"}</span> ${formatDate(app.documents.terminalReport.uploadedAt)}</p>${currentUser.role !== "student" && !app.reportReceivedAt ? `<button class="btn btn-outline btn-sm" type="button" data-receive-report="${app.id}" ${app.archived ? 'disabled title="Past term, read-only"' : ""}>Mark as received</button>` : ""}` : ""}

    <h3 class="modal-subhead">Post-approval requirements</h3>
    <div class="post-approval-documents">${postApprovalDocsHtml(app, editable)}</div>

    <h3 class="modal-subhead">Status history</h3>
    <ol class="status-history">${historyHtml}</ol>`;
}

function reviewStatusBadge(status) {
  const cls =
    status === "Valid" ? "badge-approved" : status === "Rejected" ? "badge-rejected" : "badge-under-evaluation";
  const label = status === "Valid" ? "Accepted" : status === "Rejected" ? "Rejected" : "Under review";
  return `<span class="badge ${cls}">${label}</span>`;
}

function agreementTemplateLink(app) {
  const templatePath = SCHOLARSHIP_AGREEMENT_TEMPLATES[app.scholarshipType];
  return templatePath
    ? `<a class="text-link template-link" href="${templatePath}" download target="_blank" rel="noopener">
        <i class="ti ti-download"></i> Download agreement template
      </a>`
    : "";
}

function postApprovalDocsHtml(app, editable) {
  if (app.status !== "Approved") {
    return `
      <div class="notice notice-spaced">
        <i class="ti ti-info-circle"></i>
        <span>Available once your application is approved. You will then upload your Letter of Intent and Notarized Scholarship Agreement here.</span>
      </div>`;
  }
  const isStudent = currentUser.role === "student";
  return POST_APPROVAL_SCHOLARSHIP_REQUIREMENTS.map((requirement) => {
    const info = app.postApprovalDocuments?.[requirement.key];
    const head = `
      <div class="post-approval-head">
        <strong>${requirement.label}</strong>
        ${info ? reviewStatusBadge(info.reviewStatus) : '<span class="badge badge-submitted">Not submitted</span>'}
        ${info ? `<span class="term-tag-note">Attempt ${info.attemptNo} of ${info.maxAttempts}</span>` : ""}
      </div>`;
    const fileRow = info
      ? `
      <button type="button" class="document-preview" data-file-app="${app.id}" data-file-key="${requirement.key}" title="Click to view this file">
        <i class="ti ti-file-text"></i>
        <span>${requirement.label}<small>${escapeHtml(info.name)} &middot; ${formatDate(info.uploadedAt)}</small></span>
        <i class="ti ti-eye view-icon"></i>
      </button>`
      : "";
    const reason =
      info && info.reviewStatus === "Rejected"
        ? `<div class="alert alert-error show"><strong>Rejected:</strong> ${escapeHtml(info.reviewReason || "No reason provided.")}</div>`
        : "";
    const templateLink = requirement.key === "notarizedAgreement" ? agreementTemplateLink(app) : "";
    let actions = "";
    if (!app.archived) {
      if (isStudent) {
        if (!info) {
          actions = `<button type="button" class="btn btn-primary btn-sm" data-upload-doc="${app.id}" data-doc-key="${requirement.key}"><i class="ti ti-upload"></i> Upload ${requirement.label}</button>`;
        } else if (info.reviewStatus === "Pending") {
          actions = '<p class="term-tag-note">Submitted &middot; waiting for staff review.</p>';
        } else if (info.reviewStatus === "Valid") {
          actions = '<p class="term-tag-note"><i class="ti ti-circle-check"></i> Accepted by the CSS Office.</p>';
        } else if (info.attemptNo < info.maxAttempts) {
          actions = `<button type="button" class="btn btn-primary btn-sm" data-upload-doc="${app.id}" data-doc-key="${requirement.key}"><i class="ti ti-refresh"></i> Upload resubmission (attempt ${info.attemptNo + 1} of ${info.maxAttempts})</button>`;
        } else {
          actions = '<p class="term-tag-note">No attempts left. The CSS Office can allow another resubmission.</p>';
        }
      } else if (editable) {
        const buttons = [];
        if (info && info.reviewStatus === "Pending") {
          buttons.push(`<button type="button" class="btn btn-primary btn-sm" data-review-doc="${app.id}" data-doc-key="${requirement.key}" data-review-action="Valid"><i class="ti ti-circle-check"></i> Valid</button>`);
          buttons.push(`<button type="button" class="btn btn-danger btn-sm" data-review-doc="${app.id}" data-doc-key="${requirement.key}" data-review-action="Rejected"><i class="ti ti-circle-x"></i> Reject</button>`);
        }
        if (info && info.reviewStatus === "Rejected" && info.attemptNo >= info.maxAttempts) {
          buttons.push(`<button type="button" class="btn btn-outline btn-sm" data-allow-doc="${app.id}" data-doc-key="${requirement.key}"><i class="ti ti-refresh"></i> Allow resubmission</button>`);
        }
        if (buttons.length) actions = `<div class="inline-actions">${buttons.join("")}</div>`;
      }
    }
    return `
      <div class="post-approval-doc">
        ${head}
        ${fileRow}
        ${reason}
        ${templateLink}
        ${actions}
      </div>`;
  }).join("");
}

function studentPostApprovalHtml(app) {
  if (app.status !== "Approved") return "";
  return POST_APPROVAL_SCHOLARSHIP_REQUIREMENTS.map((requirement) => {
    const info = app.postApprovalDocuments?.[requirement.key];
    if (!info) {
      return `<div>${requirement.label}: <button type="button" class="btn btn-outline btn-sm" data-upload-doc="${app.id}" data-doc-key="${requirement.key}">Upload</button></div>`;
    }
    const state =
      info.reviewStatus === "Valid"
        ? "Accepted"
        : info.reviewStatus === "Rejected"
          ? info.attemptNo < info.maxAttempts
            ? "Rejected &middot; resubmit"
            : "Rejected &middot; no attempts left"
          : "Under review";
    const resubmit =
      info.reviewStatus === "Rejected" && info.attemptNo < info.maxAttempts
        ? ` <button type="button" class="btn btn-outline btn-sm" data-upload-doc="${app.id}" data-doc-key="${requirement.key}">Resubmit</button>`
        : "";
    return `<div>${requirement.label}: ${state} (attempt ${info.attemptNo}/${info.maxAttempts}) <button type="button" class="text-link" data-file-app="${app.id}" data-file-key="${requirement.key}">View</button>${resubmit}</div>`;
  }).join("");
}

function wireDiscountEdit(container, app, onUpdated) {
  const cell = container.querySelector("[data-discount-cell]");
  if (!cell) return;
  function renderView() {
    cell.innerHTML = `<span class="discount-value">${app.discountPercent ? escapeHtml(app.discountPercent) + "%" : "\u2014"}</span> <button type="button" class="icon-btn" data-discount-action="edit" title="Edit discount"><i class="ti ti-pencil"></i></button>`;
  }
  function renderEdit() {
    cell.innerHTML = `
      <span class="inline-actions">
        <input type="number" class="discount-edit-input" min="0" max="100" step="1" value="${escapeHtml(app.discountPercent)}" />
        <button type="button" class="icon-btn" data-discount-action="save" title="Save"><i class="ti ti-check"></i></button>
        <button type="button" class="icon-btn" data-discount-action="cancel" title="Cancel"><i class="ti ti-x"></i></button>
      </span>`;
    cell.querySelector(".discount-edit-input").focus();
  }
  cell.addEventListener("click", (e) => {
    const action = e.target.closest("[data-discount-action]");
    if (!action) return;
    if (action.dataset.discountAction === "edit") {
      renderEdit();
    } else if (action.dataset.discountAction === "cancel") {
      renderView();
    } else if (action.dataset.discountAction === "save") {
      runPage(async () => {
        const value = cell.querySelector(".discount-edit-input").value.trim();
        const updated = await updateApplicationDiscount(app.id, value);
        app.discountPercent = updated.discountPercent;
        renderView();
        showToast("Tuition fee discount updated.");
        if (onUpdated) onUpdated(updated);
      });
    }
  });
}
function studentDutyHtml(app) {
  if (app.status !== "Approved") return "";
  const doc = app.documents?.terminalReport;
  const available = Number(app.dutyHours) === 80;
  return `<div>Duty rendered: ${dutyKey(app)}</div>
    ${doc ? `<div>Terminal report submitted on ${formatDate(doc.uploadedAt)} <button type="button" class="text-link" data-file-app="${app.id}" data-file-key="terminalReport">View</button> ${app.reportReceivedAt ? '<span class="badge">Received</span>' : ""}</div>` : ""}
    ${app.reportReceivedAt ? "" : available ? `<button type="button" class="btn btn-outline btn-sm" data-submit-report="${app.id}">${doc ? "Replace terminal report" : "Submit terminal report"}</button>` : '<span class="term-tag-note" aria-disabled="true">Available once your 80 hours are complete</span>'}`;
}

function dutyDetailsHtml(app) {
  if (currentUser.role === "student") return studentDutyHtml(app);
  return `${dutyKey(app)} <button type="button" class="icon-btn" data-duty-edit="${app.id}" ${app.archived ? 'disabled title="Past term, read-only"' : 'title="Edit duty rendered"'}><i class="ti ti-pencil"></i></button>`;
}

document.addEventListener("click", (event) => {
  const edit = event.target.closest("[data-duty-edit]");
  const submit = event.target.closest("[data-submit-report]");
  const receive = event.target.closest("[data-receive-report]");
  const file = event.target.closest("[data-file-app]");
  const upload = event.target.closest("[data-upload-doc]");
  const review = event.target.closest("[data-review-doc]");
  const allow = event.target.closest("[data-allow-doc]");
  if (file) {
    event.stopPropagation();
    runPage(() => viewStoredDocument(file.dataset.fileApp, file.dataset.fileKey));
  }
  if (upload && !upload.disabled) {
    runPage(() => openDocumentUploadModal(upload.dataset.uploadDoc, upload.dataset.docKey));
  }
  if (review && !review.disabled) {
    runPage(() =>
      openDocumentReviewModal(review.dataset.reviewDoc, review.dataset.docKey, review.dataset.reviewAction)
    );
  }
  if (allow && !allow.disabled) {
    runPage(() => openAllowResubmissionModal(allow.dataset.allowDoc, allow.dataset.docKey));
  }
  if (edit && !edit.disabled) runPage(async () => {
    const app = await getApplicationById(edit.dataset.dutyEdit);
    const cell = edit.closest("[data-duty-cell]");
    cell.innerHTML = `
      <select class="plain-select" id="dutyStatus" aria-label="Duty rendered status">${["Not Started", "In Progress", "Completed the 80 Hours"].map((option) => `<option ${dutyKey(app) === option ? "selected" : ""}>${option}</option>`).join("")}</select>
      <input type="number" class="discount-edit-input" id="dutyHours" aria-label="Hours rendered" min="1" max="79" value="${Math.max(1, Math.min(79, Number(app.dutyHours || 1)))}" ${dutyKey(app) !== "In Progress" ? "hidden" : ""} />
      <span class="inline-actions">
        <button type="button" class="icon-btn" id="saveDuty" title="Save"><i class="ti ti-check"></i></button>
        <button type="button" class="icon-btn" id="cancelDuty" title="Cancel"><i class="ti ti-x"></i></button>
      </span>`;
    el("dutyStatus").addEventListener("change", () => { el("dutyHours").hidden = val("dutyStatus") !== "In Progress"; });
    el("cancelDuty").addEventListener("click", () => { cell.innerHTML = dutyDetailsHtml(app); });
    el("saveDuty").addEventListener("click", () => runPage(async () => {
      const status = val("dutyStatus");
      const hours = status === "In Progress" ? Number(val("dutyHours")) : status === "Not Started" ? 0 : 80;
      if (status === "In Progress" && (!Number.isInteger(hours) || hours < 1 || hours > 79)) throw new Error("Enter hours rendered from 1 to 79.");
      await updateDutyRendered(app.id, hours, status === "Completed the 80 Hours");
      setFlash("Duty rendered updated.");
      const url = new URL(window.location.href);
      url.searchParams.set("view", app.id);
      window.location.href = url.href;
    }));
  });
  if (submit) runPage(() => openReportModal(submit.dataset.submitReport));
  if (receive && !receive.disabled) runPage(async () => {
    await receiveTerminalReport(receive.dataset.receiveReport);
    setFlash("Terminal report marked as received.");
    const url = new URL(window.location.href);
    url.searchParams.set("view", receive.dataset.receiveReport);
    window.location.href = url.href;
  });
});

async function openReportModal(appId) {
  const app = await getApplicationById(appId);
  if (!app || app.status !== "Approved" || Number(app.dutyHours) !== 80 || app.reportReceivedAt) throw new Error("Terminal report is not available or has already been received.");
  if (!el("reportModal")) document.body.insertAdjacentHTML("beforeend", `
    <div class="modal-overlay" id="reportModal"><div class="modal">
      <div class="modal-heading"><h2>Submit terminal report</h2><button type="button" class="close" data-close-modal aria-label="Close dialog"><i class="ti ti-x"></i></button></div>
      <div id="reportModalBody"></div>
    </div></div>`);
  el("reportModalBody").innerHTML = `
    ${termTag(app)}
    <p class="modal-text">${escapeHtml(app.scholarshipType)} · ${escapeHtml(app.code)}</p>
    <form id="reportForm">
      <div class="form-group"><label for="reportFile">PDF, JPG or PNG, up to ${MAX_FILE_SIZE_MB} MB</label><input type="file" id="reportFile" accept=".pdf,.jpg,.jpeg,.png" required /></div>
      <div class="alert alert-error" id="reportAlert"></div>
      <div class="modal-actions"><button type="button" class="btn btn-outline" data-close-modal>Cancel</button><button type="submit" class="btn btn-primary" id="reportSubmit">Submit</button></div>
    </form>`;
  el("reportForm").addEventListener("submit", (event) => {
    event.preventDefault();
    runPage(async () => {
      hideAlert("reportAlert");
      const file = el("reportFile").files[0];
      const check = validateFile(file);
      if (!check.valid) {
        showAlert("reportAlert", check.message);
        return;
      }
      el("reportSubmit").disabled = true;
      let path = "";
      try {
        path = storagePathFor(currentUser.id, app.id, "terminalReport", file.name);
        await uploadStoredFile(path, file);
        await submitTerminalReport(app.id, { name: file.name, path, uploadedAt: new Date().toISOString(), sizeBytes: file.size, mimeType: fileMimeType(file) });
        setFlash("Terminal report submitted.");
        window.location.href = `my-applications.html?view=${app.id}`;
      } catch (error) {
        if (path) await discardStoredFiles([path]).catch(() => {});
        showAlert("reportAlert", friendlyError(error));
        el("reportSubmit").disabled = false;
      }
    });
  });
  openModal("reportModal");
}

async function openDocumentUploadModal(appId, docKey) {
  const app = await getApplicationById(appId);
  const requirement = POST_APPROVAL_SCHOLARSHIP_REQUIREMENTS.find((item) => item.key === docKey);
  if (!app || !requirement || app.status !== "Approved") {
    throw new Error("This document is available once your application is approved.");
  }
  if (app.archived) throw new Error("This application belongs to a past term and is read-only.");
  const info = app.postApprovalDocuments?.[docKey];
  if (info && info.reviewStatus !== "Rejected") {
    throw new Error("You can only upload again after the latest file is rejected.");
  }
  if (info && info.attemptNo >= info.maxAttempts) {
    throw new Error("No attempts left. Ask the CSS Office to allow another resubmission.");
  }
  const nextAttempt = info ? info.attemptNo + 1 : 1;
  const maxAttempts = info ? info.maxAttempts : 3;
  if (!el("docUploadModal")) {
    document.body.insertAdjacentHTML(
      "beforeend",
      `
    <div class="modal-overlay" id="docUploadModal"><div class="modal">
      <div class="modal-heading"><h2>Upload document</h2><button type="button" class="close" data-close-modal aria-label="Close dialog"><i class="ti ti-x"></i></button></div>
      <div id="docUploadModalBody"></div>
    </div></div>`
    );
  }
  el("docUploadModalBody").innerHTML = `
    ${termTag(app)}
    <p class="modal-text">${escapeHtml(requirement.label)} &middot; ${escapeHtml(app.code)}</p>
    <p class="term-tag-note">Attempt ${nextAttempt} of ${maxAttempts}</p>
    ${
      info && info.reviewStatus === "Rejected"
        ? `<div class="alert alert-error show"><strong>Previous file rejected:</strong> ${escapeHtml(info.reviewReason || "No reason provided.")}</div>`
        : ""
    }
    ${docKey === "notarizedAgreement" ? agreementTemplateLink(app) : ""}
    <form id="docUploadForm">
      <div class="form-group"><label for="docUploadFile">PDF, JPG or PNG, up to ${MAX_FILE_SIZE_MB} MB</label><input type="file" id="docUploadFile" accept=".pdf,.jpg,.jpeg,.png" required /></div>
      <div class="alert alert-error" id="docUploadAlert"></div>
      <div class="modal-actions"><button type="button" class="btn btn-outline" data-close-modal>Cancel</button><button type="submit" class="btn btn-primary" id="docUploadSubmit"><i class="ti ti-upload"></i> Upload</button></div>
    </form>`;
  el("docUploadForm").onsubmit = (event) => {
    event.preventDefault();
    runPage(async () => {
      hideAlert("docUploadAlert");
      const file = el("docUploadFile").files[0];
      const check = validateFile(file);
      if (!check.valid) {
        showAlert("docUploadAlert", check.message);
        return;
      }
      el("docUploadSubmit").disabled = true;
      let path = "";
      try {
        path = storagePathFor(currentUser.id, app.id, docKey, file.name);
        await uploadStoredFile(path, file);
        await submitApplicationDocument(app.id, docKey, {
          name: file.name,
          path,
          uploadedAt: new Date().toISOString(),
          sizeBytes: file.size,
          mimeType: fileMimeType(file),
        });
        setFlash(`${requirement.label} submitted for review.`);
        window.location.href = `my-applications.html?view=${app.id}`;
      } catch (error) {
        if (path) await discardStoredFiles([path]).catch(() => {});
        showAlert("docUploadAlert", friendlyError(error));
        el("docUploadSubmit").disabled = false;
      }
    });
  };
  openModal("docUploadModal");
}

function ensureStaffDocModal() {
  if (el("staffDocModal")) return;
  document.body.insertAdjacentHTML(
    "beforeend",
    `
  <div class="modal-overlay" id="staffDocModal"><div class="modal modal-sm">
    <div class="modal-heading"><h2 id="staffDocTitle">Document</h2><button type="button" class="close" data-close-modal aria-label="Close dialog"><i class="ti ti-x"></i></button></div>
    <div id="staffDocBody"></div>
  </div></div>`
  );
}

async function openDocumentReviewModal(appId, docKey, action) {
  const app = await getApplicationById(appId);
  const requirement = POST_APPROVAL_SCHOLARSHIP_REQUIREMENTS.find((item) => item.key === docKey);
  const info = app?.postApprovalDocuments?.[docKey];
  if (!app || !requirement || !info || info.reviewStatus !== "Pending") {
    throw new Error("Only the latest submission, while under review, can be reviewed.");
  }
  const rejecting = action === "Rejected";
  ensureStaffDocModal();
  el("staffDocTitle").textContent = rejecting
    ? `Reject ${requirement.label}`
    : `Accept ${requirement.label}`;
  el("staffDocBody").innerHTML = `
    <p class="modal-text">${escapeHtml(app.code)} &middot; attempt ${info.attemptNo} of ${info.maxAttempts} &middot; ${escapeHtml(info.name)}</p>
    <form id="staffDocForm">
      ${
        rejecting
          ? `
      <div class="form-group">
        <label for="staffDocReason">Reason (required, shown to the student)</label>
        <div class="input-wrap"><i class="ti ti-notes"></i><textarea id="staffDocReason" placeholder="e.g. Not notarized / Letter is unsigned"></textarea></div>
      </div>`
          : `<p class="modal-text">Mark this submission as accepted? The student will be notified.</p>`
      }
      <div class="alert alert-error" id="staffDocAlert"></div>
      <div class="modal-actions">
        <button type="button" class="btn btn-outline" data-close-modal>Cancel</button>
        <button type="submit" class="btn ${rejecting ? "btn-danger" : "btn-primary"}" id="staffDocSubmit">${rejecting ? "Reject" : "Mark valid"}</button>
      </div>
    </form>`;
  el("staffDocForm").onsubmit = (event) => {
    event.preventDefault();
    runPage(async () => {
      hideAlert("staffDocAlert");
      const reason = el("staffDocReason")?.value.trim() || "";
      if (rejecting && !reason) {
        showAlert("staffDocAlert", "Please provide a reason before rejecting this document.");
        return;
      }
      el("staffDocSubmit").disabled = true;
      try {
        await reviewApplicationDocument(app.id, docKey, rejecting ? "Rejected" : "Valid", reason);
        setFlash(`${requirement.label} reviewed.`);
        window.location.href = `staff-applications.html?view=${app.id}`;
      } catch (error) {
        showAlert("staffDocAlert", friendlyError(error));
        el("staffDocSubmit").disabled = false;
      }
    });
  };
  openModal("staffDocModal");
}

async function openAllowResubmissionModal(appId, docKey) {
  const app = await getApplicationById(appId);
  const requirement = POST_APPROVAL_SCHOLARSHIP_REQUIREMENTS.find((item) => item.key === docKey);
  const info = app?.postApprovalDocuments?.[docKey];
  if (!app || !requirement || !info || info.reviewStatus !== "Rejected" || info.attemptNo < info.maxAttempts) {
    throw new Error("Resubmission can only be allowed once all attempts are used.");
  }
  ensureStaffDocModal();
  el("staffDocTitle").textContent = `Allow resubmission - ${requirement.label}`;
  el("staffDocBody").innerHTML = `
    <p class="modal-text">${escapeHtml(app.code)} &middot; the student used all ${info.maxAttempts} attempts. This adds one extra attempt.</p>
    <form id="staffDocForm">
      <div class="form-group">
        <label for="staffDocReason">Reason (required, shown to the student)</label>
        <div class="input-wrap"><i class="ti ti-notes"></i><textarea id="staffDocReason" placeholder="Why is another resubmission allowed?"></textarea></div>
      </div>
      <div class="alert alert-error" id="staffDocAlert"></div>
      <div class="modal-actions">
        <button type="button" class="btn btn-outline" data-close-modal>Cancel</button>
        <button type="submit" class="btn btn-primary" id="staffDocSubmit"><i class="ti ti-refresh"></i> Allow resubmission</button>
      </div>
    </form>`;
  el("staffDocForm").onsubmit = (event) => {
    event.preventDefault();
    runPage(async () => {
      hideAlert("staffDocAlert");
      const reason = el("staffDocReason").value.trim();
      if (!reason) {
        showAlert("staffDocAlert", "Please provide a reason for allowing another resubmission.");
        return;
      }
      el("staffDocSubmit").disabled = true;
      try {
        await allowDocumentResubmission(app.id, docKey, reason);
        setFlash(`Extra resubmission allowed for ${requirement.label}.`);
        window.location.href = `staff-applications.html?view=${app.id}`;
      } catch (error) {
        showAlert("staffDocAlert", friendlyError(error));
        el("staffDocSubmit").disabled = false;
      }
    });
  };
  openModal("staffDocModal");
}
