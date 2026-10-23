const STATUSES = ["Submitted", "Under Evaluation", "Approved", "Rejected"];
const TRIMESTERS = ["1st Trimester", "2nd Trimester", "3rd Trimester"];
const DEFAULT_TERM = { trimester: "1st Trimester", academicYear: "2026\u20132027" };
const SCHOLARSHIP_TYPES = [
  "Academic Scholarship",
  "Entrance Exam Scholarship",
  "4Ps Scholarship",
  "Urdanetarian Scholarship",
  "RPSEA Scholarship",
  "SOC Scholarship",
  "BSA Scholarship",
  "New Program Scholarship",
];

function makeTermLabel(term) {
  if (!term || !term.trimester) return "";
  return `${term.trimester}, AY ${term.academicYear}`;
}

async function currentTermLabel() {
  const term = await getCurrentTerm();
  return term.label || makeTermLabel(term);
}

function friendlyError(error) {
  return error && error.message ? error.message : String(error || "Something went wrong.");
}

function sameEmail(a, b) {
  return String(a || "").trim().toLowerCase() === String(b || "").trim().toLowerCase();
}

function apiUrl(path) {
  const base = String(window.SCHOLARSHIP_API_BASE_URL || "").replace(/\/$/, "");
  return `${base}/api${path}`;
}

async function apiRequest(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const requestOptions = { ...options, credentials: "include", headers };
  if (requestOptions.body && !(requestOptions.body instanceof FormData) && typeof requestOptions.body !== "string") {
    headers.set("Content-Type", "application/json");
    requestOptions.body = JSON.stringify(requestOptions.body);
  } else if (requestOptions.body && typeof requestOptions.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(apiUrl(path), requestOptions);
  let data = {};
  try {
    data = response.status === 204 ? {} : await response.json();
  } catch (error) {
    data = {};
  }
  if (!response.ok) {
    const message = data.error || data.detail || "The request could not be completed.";
    const requestError = new Error(typeof message === "string" ? message : "Please check the submitted information.");
    requestError.status = response.status;
    throw requestError;
  }
  return data;
}

async function getCurrentUser() {
  try {
    const result = await apiRequest("/auth/me");
    return result.user || null;
  } catch (error) {
    if (error.status === 401) return null;
    throw error;
  }
}

async function signIn(email, password) {
  try {
    return await apiRequest("/auth/login", { method: "POST", body: { email, password } });
  } catch (error) {
    return { error: friendlyError(error) };
  }
}

async function signOutUser() {
  try {
    await apiRequest("/auth/logout", { method: "POST", body: {} });
  } catch (error) {
    return;
  }
}

async function signUpStudent(details) {
  try {
    return await apiRequest("/auth/register", { method: "POST", body: details });
  } catch (error) {
    return { error: friendlyError(error) };
  }
}

async function sendPasswordReset(email) {
  try {
    return await apiRequest("/auth/password-reset/request", { method: "POST", body: { email } });
  } catch (error) {
    return { error: friendlyError(error) };
  }
}

async function setNewPassword(email, newPassword) {
  try {
    return await apiRequest("/auth/password-reset/confirm", { method: "POST", body: { email, newPassword } });
  } catch (error) {
    return { error: friendlyError(error) };
  }
}

async function changeOwnPassword(user, currentPassword, newPassword) {
  try {
    return await apiRequest("/users/me/password", {
      method: "POST",
      body: { currentPassword, newPassword },
    });
  } catch (error) {
    return { error: friendlyError(error) };
  }
}

async function updateOwnProfile(userId, patch) {
  return apiRequest("/users/me", { method: "PATCH", body: patch });
}

async function allStaffAccounts() {
  return apiRequest("/admin/accounts");
}

async function createStaffAccount(details) {
  try {
    return await apiRequest("/admin/accounts", { method: "POST", body: details });
  } catch (error) {
    return { error: friendlyError(error) };
  }
}

async function updateStaffAccount(userId, details) {
  try {
    return await apiRequest(`/admin/accounts/${encodeURIComponent(userId)}`, {
      method: "PUT",
      body: details,
    });
  } catch (error) {
    return { error: friendlyError(error) };
  }
}

async function deleteStaffAccount(userId) {
  try {
    return await apiRequest(`/admin/accounts/${encodeURIComponent(userId)}`, { method: "DELETE" });
  } catch (error) {
    return { error: friendlyError(error) };
  }
}

async function getCurrentTerm() {
  return apiRequest("/terms/current");
}

async function setCurrentTerm(trimester, academicYear) {
  try {
    return await apiRequest("/terms/current", {
      method: "PUT",
      body: { trimester, academicYear },
    });
  } catch (error) {
    return { error: friendlyError(error) };
  }
}

async function getAllApplications() {
  return apiRequest("/staff/applications/history");
}

async function getActiveApplications() {
  return apiRequest("/staff/applications");
}

async function getApplicationsForStudent(studentUserId) {
  return apiRequest("/applications");
}

async function getActiveApplicationsForStudent(studentUserId) {
  return apiRequest("/applications?active=true");
}

async function getApplicationById(id) {
  try {
    return await apiRequest(`/applications/${encodeURIComponent(id)}`);
  } catch (error) {
    if (error.status === 404) return null;
    throw error;
  }
}

async function createApplication(application) {
  return apiRequest("/applications", {
    method: "POST",
    body: {
      id: application.id,
      termId: application.termId || null,
      program: application.program,
      yearLevel: application.yearLevel,
      scholarshipType: application.scholarshipType,
      documents: application.documents,
    },
  });
}

async function updateApplicationStatus(appId, status, remarks, discountPercent) {
  return apiRequest(`/staff/applications/${encodeURIComponent(appId)}/status`, {
    method: "PATCH",
    body: {
      status,
      remarks: remarks || "",
      discountPercent: discountPercent === "" || discountPercent === undefined ? null : Number(discountPercent),
    },
  });
}

async function updateApplicationDiscount(appId, discountPercent) {
  return apiRequest(`/staff/applications/${encodeURIComponent(appId)}/discount`, {
    method: "PATCH",
    body: {
      discountPercent: discountPercent === "" || discountPercent === undefined ? null : Number(discountPercent),
    },
  });
}

async function reopenApplication(appId, reason) {
  return apiRequest(`/admin/applications/${encodeURIComponent(appId)}/reopen`, {
    method: "POST",
    body: { reason },
  });
}

async function deleteApplication(appId) {
  return apiRequest(`/staff/applications/${encodeURIComponent(appId)}`, { method: "DELETE" });
}

async function getNotificationsForUser(userId) {
  return apiRequest("/notifications");
}

async function unreadNotificationCount(userId) {
  const result = await apiRequest("/notifications/unread-count");
  return Number(result.count || 0);
}

async function markNotificationRead(id) {
  return apiRequest(`/notifications/${encodeURIComponent(id)}/read`, { method: "PATCH", body: {} });
}

async function markAllNotificationsRead(userId) {
  return apiRequest("/notifications/read-all", { method: "POST", body: {} });
}

async function getAcademicTerms() {
  return apiRequest("/terms");
}

async function saveTermScholarships(termId, scholarships) {
  return apiRequest(`/terms/${encodeURIComponent(termId)}/scholarships`, { method: "PUT", body: { scholarships } });
}

async function updateDutyRendered(appId, hours, completed) {
  return apiRequest(`/admin/applications/${encodeURIComponent(appId)}/duty`, { method: "PATCH", body: { hours, completed } });
}

async function submitTerminalReport(appId, document) {
  return apiRequest(`/applications/${encodeURIComponent(appId)}/terminal-report`, { method: "POST", body: document });
}

async function receiveTerminalReport(appId) {
  return apiRequest(`/staff/applications/${encodeURIComponent(appId)}/terminal-report/receive`, { method: "POST", body: {} });
}
