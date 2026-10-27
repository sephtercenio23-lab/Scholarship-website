function safeFileName(name) {
  return String(name || "").replace(/[^A-Za-z0-9._-]/g, "_");
}

function storagePathFor(userId, appId, requirementKey, fileName) {
  return `${userId}/${appId}/${requirementKey}/${newId()}_${safeFileName(fileName)}`;
}

function fileMimeType(file) {
  if (file && file.type) return file.type;
  const lowerName = String(file && file.name || "").toLowerCase();
  if (lowerName.endsWith(".pdf")) return "application/pdf";
  if (lowerName.endsWith(".jpg") || lowerName.endsWith(".jpeg")) return "image/jpeg";
  if (lowerName.endsWith(".png")) return "image/png";
  return "application/octet-stream";
}

async function uploadStoredFile(path, file) {
  const parts = path.split("/");
  if (parts.length !== 4) throw new Error("The document upload path is invalid.");
  const result = await apiRequest("/files/upload-url", {
    method: "POST",
    body: {
      path,
      applicationId: parts[1],
      requirementKey: parts[2],
      fileName: file.name,
      contentType: fileMimeType(file),
      sizeBytes: file.size,
    },
  });
  const form = new FormData();
  form.append("cacheControl", "3600");
  form.append("", file, file.name);
  const response = await fetch(result.signedUrl, { method: "PUT", body: form });
  if (!response.ok) {
    let message = "The document could not be uploaded to secure storage.";
    try {
      const data = await response.json();
      message = data.message || data.error || message;
    } catch (error) {
      message = "The document could not be uploaded to secure storage.";
    }
    throw new Error(message);
  }
  return result.path;
}

async function downloadStoredFile(path) {
  if (!path) return null;
  try {
    const result = await apiRequest(`/files/download-url?path=${encodeURIComponent(path)}`);
    const response = await fetch(result.signedUrl);
    if (!response.ok) return null;
    return await response.blob();
  } catch (error) {
    return null;
  }
}

async function deleteApplicationFiles(app) {
  const paths = [
    ...Object.values((app && app.documents) || {}).map((document) => document && document.path),
    ...((app && app.submissionPaths) || []),
  ].filter(Boolean);
  const uniquePaths = [...new Set(paths)];
  if (!uniquePaths.length) return;
  await apiRequest("/files/delete", { method: "POST", body: { paths: uniquePaths } });
}

async function discardStoredFiles(paths) {
  if (!paths || !paths.length) return;
  await apiRequest("/files/discard", { method: "POST", body: { paths } });
}

function makeSamplePdf(title) {
  const safe = title.replace(/[^A-Za-z0-9 .,_-]/g, "");
  const content =
    "BT /F1 20 Tf 60 720 Td (" + safe + ") Tj " +
    "0 -34 Td /F1 12 Tf (Sample placeholder for the demo data. This is not a real uploaded file.) Tj ET";
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    "<< /Length " + content.length + " >>\nstream\n" + content + "\nendstream",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let pdf = "%PDF-1.4\n";
  const offsets = [];
  objects.forEach((body, i) => {
    offsets.push(pdf.length);
    pdf += (i + 1) + " 0 obj\n" + body + "\nendobj\n";
  });
  const xrefStart = pdf.length;
  pdf += "xref\n0 " + (objects.length + 1) + "\n0000000000 65535 f \n";
  offsets.forEach((offset) => {
    pdf += String(offset).padStart(10, "0") + " 00000 n \n";
  });
  pdf += "trailer\n<< /Size " + (objects.length + 1) + " /Root 1 0 R >>\nstartxref\n" + xrefStart + "\n%%EOF";
  return new Blob([pdf], { type: "application/pdf" });
}

let currentFileUrl = null;

function ensureFileModal() {
  if (el("fileModal")) return;
  const wrapper = document.createElement("div");
  wrapper.innerHTML = `
    <div class="modal-overlay" id="fileModal">
      <div class="modal modal-xl">
        <div class="modal-heading">
          <h2 id="fileModalTitle">Document</h2>
          <button type="button" class="close" data-close-modal aria-label="Close dialog"><i class="ti ti-x"></i></button>
        </div>
        <div class="file-viewer" id="fileViewer"></div>
        <div class="modal-actions">
          <a class="btn btn-outline" id="fileOpenLink" target="_blank" rel="noopener"><i class="ti ti-external-link"></i> Open in new tab</a>
          <a class="btn btn-primary" id="fileDownloadLink"><i class="ti ti-download"></i> Download</a>
        </div>
      </div>
    </div>`;
  document.body.appendChild(wrapper.firstElementChild);
}

async function viewStoredDocument(appId, requirementKey) {
  const app = await getApplicationById(appId);
  const doc = app && app.documents && app.documents[requirementKey];
  if (!doc) return;
  const requirement = SCHOLARSHIP_REQUIREMENTS.find((item) => item.key === requirementKey) || { label: "Terminal report" };
  let file = doc.sample
    ? makeSamplePdf(requirement.label + " - " + doc.name)
    : await downloadStoredFile(doc.path);
  if (!file) {
    showToast("This file could not be opened. It may have been removed from secure storage.", true);
    return;
  }
  ensureFileModal();
  if (currentFileUrl) URL.revokeObjectURL(currentFileUrl);
  currentFileUrl = URL.createObjectURL(file);
  const lowerName = doc.name.toLowerCase();
  const isPdf = file.type === "application/pdf" || lowerName.endsWith(".pdf");
  const isImage = (file.type || "").startsWith("image/") || /\.(jpe?g|png)$/.test(lowerName);
  el("fileModalTitle").textContent = requirement.label;
  if (isPdf) {
    el("fileViewer").innerHTML = `<iframe class="file-frame" title="${escapeHtml(doc.name)}"></iframe>`;
    el("fileViewer").querySelector("iframe").src = currentFileUrl;
  } else if (isImage) {
    el("fileViewer").innerHTML = `<img class="file-image" alt="${escapeHtml(doc.name)}" />`;
    el("fileViewer").querySelector("img").src = currentFileUrl;
  } else {
    el("fileViewer").innerHTML = `<p class="modal-text">This file type cannot be previewed. Use Download.</p>`;
  }
  el("fileOpenLink").href = currentFileUrl;
  el("fileDownloadLink").href = currentFileUrl;
  el("fileDownloadLink").download = doc.name;
  openModal("fileModal");
}
