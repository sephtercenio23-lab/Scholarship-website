function approvalProgressHtml(app) {
  if (!app || !(isPendingApprovalStatus(app.status) || isApprovedStatus(app.status) || app.status === "Rejected")) return "";
  const approvals = app.approvals || {};
  const rows = APPROVAL_STAGES.map((stage) => {
    const entry = approvals[stage.key];
    const done = Boolean(entry && entry.by);
    return `<dt>${stage.label}${stage.office ? " · " + stage.office : ""}</dt><dd>${done ? `<i class="ti ti-circle-check"></i> ${escapeHtml(entry.by)}${entry.at ? " · " + formatDate(entry.at) : ""}` : '<span class="badge badge-submitted">Pending</span>'}</dd>`;
  }).join("");
  return `
    <h3 class="modal-subhead">Approval progress</h3>
    <dl class="detail-list">${rows}</dl>
    ${isPendingApprovalStatus(app.status) || isChangedAfterFinance(app) ? '<p class="term-tag-note">The student will see Approved only after all three approvals are complete.</p>' : ""}`;
}

// Shared details view used by the student's My Applications and the staff review modal.
function applicationDetailsHtml(app, editable) {
  const canEditDiscountRole =
    typeof currentUser === "object" &&
    currentUser !== null &&
    ["staff", "admin", "super_admin"].includes(currentUser.role);
  const discountEditableStatus =
    typeof isDiscountEditableStatus === "function"
      ? isDiscountEditableStatus(app.status)
      : app.status === "Endorsed by Staff" ||
        app.status === "Approved by President" ||
        isApprovedStatus(app.status);
  const discountEditable = editable && canEditDiscountRole && discountEditableStatus && !app.archived;
  const gradeRemarks = [
    app.hasFailingGrade ? "Failing grade" : "",
    app.hasIncompleteGrade ? "INC" : "",
    app.hasDroppedGrade ? "Dropped" : "",
  ].filter(Boolean);
  const gradeRemarksHtml = gradeRemarks.length
    ? `<dt>Grade remarks</dt><dd>${escapeHtml(gradeRemarks.join(", "))}</dd>`
    : "";
  const documentsHtml = INITIAL_SCHOLARSHIP_REQUIREMENTS.map((requirement) => {
    const doc = app.documents[requirement.key];
    if (doc && doc.name) {
      return `
        <button type="button" class="document-preview" data-file-app="${app.id}" data-file-key="${requirement.key}" title="Click to view this file">
          <i class="ti ti-file-text"></i>
          <span>${requirement.label}<small>${escapeHtml(doc.name)}</small></span>
          <i class="ti ti-eye view-icon"></i>
        </button>`;
    }
    return `
      <div class="document-preview document-missing">
        <i class="ti ti-file-off"></i>
        <span>${requirement.label}<small>Not submitted</small></span>
      </div>`;
  }).join("");
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
      ${applicationStatusBadges(app)}
    </div>

    <dl class="detail-list">
      <dt>Student</dt><dd>${escapeHtml(app.studentName)} (${escapeHtml(app.studentId)})</dd>
      <dt>Email</dt><dd>${escapeHtml(app.universityEmail)}</dd>
      <dt>Program / year</dt><dd>${escapeHtml(app.program)} &middot; ${escapeHtml(app.yearLevel)}</dd>
      ${gradeRemarksHtml}
      <dt>Term</dt><dd>${escapeHtml(app.term || "\u2014")}</dd>
      <dt>Submitted</dt><dd>${formatDate(app.dateSubmitted)}</dd>
      <dt>Tuition fee discount</dt><dd data-discount-cell><span class="discount-value">${app.discountPercent !== null && app.discountPercent !== undefined ? escapeHtml(app.discountPercent) + "%" : "\u2014"}</span>${discountEditable ? ' <button type="button" class="icon-btn" data-discount-action="edit" title="Edit discount"><i class="ti ti-pencil"></i></button>' : ""}</dd>
      <dt>Past term discount</dt><dd>${pastDiscountLabel(app.pastDiscount)}</dd>
      ${app.financeSentAt ? `<dt>Sent to Finance</dt><dd>${formatDate(app.financeSentAt)} &middot; approved scholars are emailed to Finance in Excel format</dd>` : ""}
      ${isChangedAfterFinance(app) ? `<dt>Finance flag</dt><dd class="finance-flag-dd"><span class="badge badge-changed-after-finance">${CHANGED_AFTER_FINANCE}</span><span>Edited after Finance received this scholar, so the three approvals run again.</span></dd>` : ""}
    </dl>

    ${approvalProgressHtml(app)}
    <h3 class="modal-subhead">Submitted requirements</h3>
    <div class="submitted-documents">${documentsHtml}</div>

    <h3 class="modal-subhead">Post-approval requirements</h3>
    <div class="post-approval-documents">${postApprovalDocsHtml(app, editable)}</div>
    ${appealSectionHtml(app)}`;
}

function appealStatusBadge(status) {
  const cls =
    status === "Accepted" ? "badge-approved" : status === "Declined" ? "badge-rejected" : "badge-under-evaluation";
  return `<span class="badge ${cls}">${escapeHtml(status)}</span>`;
}

function appealSectionHtml(app) {
  const appeal = app.appeal;
  if (!appeal) {
    if (currentUser.role === "student" && app.status === "Rejected" && !app.archived) {
      return `
      <h3 class="modal-subhead">Appeal this decision</h3>
      <div class="notice notice-spaced">
        <i class="ti ti-info-circle"></i>
        <span>If you believe this decision should be reviewed, submit one appeal explaining why. The CSS Office will respond here and by email.</span>
      </div>
      <div class="form-group">
        <label for="appealReason">Reason for appeal (required, up to 1000 characters)</label>
        <div class="input-wrap"><i class="ti ti-notes"></i><textarea id="appealReason" maxlength="1000" placeholder="Explain why you are appealing this rejection..."></textarea></div>
      </div>
      <div class="alert alert-error" id="appealAlert"></div>
      <button type="button" class="btn btn-primary btn-sm" data-appeal-submit="${app.id}"><i class="ti ti-send"></i> Submit appeal</button>`;
    }
    return "";
  }
  const decided = appeal.status !== "Pending";
  return `
  <h3 class="modal-subhead">Appeal</h3>
  <div class="notice notice-spaced">
    <div class="post-approval-head">
      <strong>Student appeal</strong>
      ${appealStatusBadge(appeal.status)}
      <span class="term-tag-note">Submitted ${formatDate(appeal.createdAt)}</span>
    </div>
    <p class="modal-text">${escapeHtml(appeal.reason)}</p>
    ${decided ? `
      <div class="alert ${appeal.status === "Accepted" ? "alert-success" : "alert-error"} show">
        <strong>${escapeHtml(appeal.status)}${appeal.respondedBy ? " &middot; " + escapeHtml(appeal.respondedBy) : ""}</strong>
        ${appeal.response ? `<br>${escapeHtml(appeal.response)}` : ""}
      </div>
      <p class="term-tag-note">Responded ${formatDateTime(appeal.respondedAt)}</p>`
      : '<p class="term-tag-note"><i class="ti ti-hourglass"></i> Waiting for the CSS Office response.</p>'}
  </div>`;
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
  if (!postApprovalDocsUnlocked(app)) {
    return `
      <div class="notice notice-spaced">
        <i class="ti ti-info-circle"></i>
        <span>Available once your application is endorsed by the CSS Office. You will then upload your Letter of Intent and Notarized Scholarship Agreement here.</span>
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
  if (!postApprovalDocsUnlocked(app)) return "";
  const rows = POST_APPROVAL_SCHOLARSHIP_REQUIREMENTS.map((requirement) => {
    const info = app.postApprovalDocuments?.[requirement.key];
    if (!info) {
      return `
      <div class="compact-doc-row">
        <span class="compact-doc-name">${requirement.label}</span>
        <span class="compact-doc-foot">
          <span class="compact-doc-state">Not submitted</span>
          ${app.archived ? "" : `<button type="button" class="text-link" data-upload-doc="${app.id}" data-doc-key="${requirement.key}">Upload</button>`}
        </span>
      </div>`;
    }
    const stateClass =
      info.reviewStatus === "Valid"
        ? "state-accepted"
        : info.reviewStatus === "Rejected"
          ? "state-rejected"
          : "state-pending";
    const stateLabel =
      info.reviewStatus === "Valid"
        ? `Accepted &middot; ${info.attemptNo}/${info.maxAttempts}`
        : info.reviewStatus === "Rejected"
          ? info.attemptNo < info.maxAttempts
            ? `Rejected &middot; ${info.attemptNo}/${info.maxAttempts}`
            : "Rejected &middot; no attempts left"
          : `Under review &middot; ${info.attemptNo}/${info.maxAttempts}`;
    const resubmit =
      !app.archived && info.reviewStatus === "Rejected" && info.attemptNo < info.maxAttempts
        ? `<button type="button" class="text-link" data-upload-doc="${app.id}" data-doc-key="${requirement.key}">Resubmit</button>`
        : "";
    return `
      <div class="compact-doc-row">
        <span class="compact-doc-name">${requirement.label}</span>
        <span class="compact-doc-foot">
          <span class="compact-doc-state ${stateClass}">${stateLabel}</span>
          <button type="button" class="text-link" data-file-app="${app.id}" data-file-key="${requirement.key}">View</button>
          ${resubmit}
        </span>
      </div>`;
  }).join("");
  return `
  <div class="post-approval-compact">
    <p class="compact-section-label">Post-approval documents</p>
    ${rows}
  </div>`;
}

function wireDiscountEdit(container, app, onUpdated) {
  const cell = container.querySelector("[data-discount-cell]");
  if (!cell) return;
  function renderView() {
    cell.innerHTML = `<span class="discount-value">${app.discountPercent !== null && app.discountPercent !== undefined ? escapeHtml(app.discountPercent) + "%" : "\u2014"}</span> <button type="button" class="icon-btn" data-discount-action="edit" title="Edit discount"><i class="ti ti-pencil"></i></button>`;
  }
  function renderEdit() {
    cell.innerHTML = `
      <span class="inline-actions">
        <input type="number" class="discount-edit-input" aria-label="Tuition fee discount percent" min="0" max="100" step="1" value="${escapeHtml(app.discountPercent)}" />
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
        setButtonBusy(action, "");
        let updated = null;
        try {
          updated = await updateApplicationDiscount(app.id, value);
        } catch (error) {
          clearButtonBusy(action);
          showToast(friendlyError(error), true);
          return;
        }
        app.discountPercent = updated.discountPercent;
        renderView();
        showToast("Tuition fee discount updated.");
        if (onUpdated) onUpdated(updated);
      });
    }
  });
}
document.addEventListener("click", (event) => {
  const file = event.target.closest("[data-file-app]");
  const upload = event.target.closest("[data-upload-doc]");
  const review = event.target.closest("[data-review-doc]");
  const allow = event.target.closest("[data-allow-doc]");
  const appealSubmit = event.target.closest("[data-appeal-submit]");
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
  if (appealSubmit && !appealSubmit.disabled) {
    runPage(async () => {
      const reason = val("appealReason");
      if (!reason) {
        showAlert("appealAlert", "Please provide a reason for your appeal.");
        return;
      }
      setButtonBusy(appealSubmit, "Submitting...");
      try {
        await submitApplicationAppeal(appealSubmit.dataset.appealSubmit, reason);
      } catch (error) {
        clearButtonBusy(appealSubmit);
        showAlert("appealAlert", friendlyError(error));
        return;
      }
      setFlash("Appeal submitted. The CSS Office will respond here and by email.");
      window.location.href = `my-applications.html?view=${appealSubmit.dataset.appealSubmit}`;
    });
  }
});

async function openDocumentUploadModal(appId, docKey) {
  const app = await getApplicationById(appId);
  const requirement = POST_APPROVAL_SCHOLARSHIP_REQUIREMENTS.find((item) => item.key === docKey);
  if (!app || !requirement || !postApprovalDocsUnlocked(app)) {
    throw new Error("This document is available once your application is endorsed by the CSS Office.");
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
      <div class="form-group"><label for="docUploadFile">${requirement.label} file (PDF, JPG or PNG, up to ${MAX_FILE_SIZE_MB} MB)</label><input type="file" id="docUploadFile" accept=".pdf,.jpg,.jpeg,.png" required /></div>
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
      setButtonBusy(el("docUploadSubmit"), "Uploading...");
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
        clearButtonBusy(el("docUploadSubmit"));
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
      setButtonBusy(el("staffDocSubmit"), rejecting ? "Rejecting..." : "Saving...");
      try {
        await reviewApplicationDocument(app.id, docKey, rejecting ? "Rejected" : "Valid", reason);
        setFlash(`${requirement.label} reviewed.`);
        const url = new URL(window.location.href);
        url.searchParams.set("view", app.id);
        window.location.href = url.href;
      } catch (error) {
        showAlert("staffDocAlert", friendlyError(error));
        clearButtonBusy(el("staffDocSubmit"));
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
      setButtonBusy(el("staffDocSubmit"), "Allowing...");
      try {
        await allowDocumentResubmission(app.id, docKey, reason);
        setFlash(`Extra resubmission allowed for ${requirement.label}.`);
        const url = new URL(window.location.href);
        url.searchParams.set("view", app.id);
        window.location.href = url.href;
      } catch (error) {
        showAlert("staffDocAlert", friendlyError(error));
        clearButtonBusy(el("staffDocSubmit"));
      }
    });
  };
  openModal("staffDocModal");
}
