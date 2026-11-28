const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const test = require("node:test");
const vm = require("node:vm");

const dataSource = readFileSync("PU scholarship system/js/data.js", "utf8");
const source = readFileSync("PU scholarship system/js/staff-applications.js", "utf8");

function makeSelect(id) {
  return {
    id,
    value: "",
    innerHTML: "",
    dataset: {},
    hidden: false,
    disabled: false,
    listeners: {},
    addEventListener(event, fn) {
      this.listeners[event] = fn;
    },
  };
}

function makeHarness(matchesViewingFn, selectedTermFn) {
  const createdHtml = {};
  const elements = {
    viewingTerm: makeSelect("viewingTerm"),
    searchBox: { value: "" },
    typeFilter: makeSelect("typeFilter"),
    dateFilter: { value: "" },
    applicationRows: { innerHTML: "" },
    evalArea: { innerHTML: "" },
    filterCount: { textContent: "" },
    emptyState: { classList: { toggle() {} } },
    clearFiltersBtn: {
      insertAdjacentHTML(_pos, html) {
        const match = html.match(/id="([^"]+)"/);
        if (match) {
          elements[match[1]] = makeSelect(match[1]);
          createdHtml[match[1]] = html;
        }
      },
    },
  };
  const context = vm.createContext({
    runPage: () => {},
    el: (id) => elements[id],
    val: (id) => String(elements[id]?.value || "").trim(),
    document: { querySelectorAll: () => [] },
    escapeHtml: (value) =>
      String(value).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch])),
    matchesViewing: matchesViewingFn,
    selectedViewingTerm: selectedTermFn,
    sortApplications: (apps) => [...apps],
    dutyKey: () => "Not Started",
    reportState: () => "Not Yet Available",
    termTag: (app) => app.term || "",
    formatDate: () => "Nov 19, 2026",
    localDateStr: () => "2026-11-19",
    statusBadge: (status) => status,
    pastDiscountLabel: (value) => (value === null || value === undefined || value === "" ? "\u2014" : String(value) + "%"),
    isApprovedStatus: (status) => ["Approved", "Approved by Executive President", "Sent to Finance", "Exported"].includes(status),
    isPendingApprovalStatus: (status) => ["Under Evaluation", "Endorsed by Staff", "Approved by President"].includes(status),
    isChangedAfterFinance: (app) => Boolean(app && app.changedAfterFinance),
    CHANGED_AFTER_FINANCE: "Changed after sent to Finance",
    applicationStatusBadges: (app) => app.status,
  });
  vm.runInContext(dataSource, context);
  vm.runInContext(source, context);
  context.initExtraFilters();
  return { context, elements, createdHtml };
}

test("the three reviewers can start evaluation, but starting does not skip staff endorsement", () => {
  const { context, elements } = makeHarness();
  for (const role of ["staff", "president", "executive_president"]) {
    vm.runInContext(`currentUser = {role: "${role}"}`, context);
    context.showEvaluation({ status: "Submitted" });
    assert.match(elements.evalArea.innerHTML, /data-action="start"/);
    context.showEvaluation({ status: "Submitted", archived: true });
    assert.doesNotMatch(elements.evalArea.innerHTML, /data-action="start"/);
    if (role !== "staff") {
      context.showEvaluation({ status: "Under Evaluation", approvals: {} });
      assert.match(elements.evalArea.innerHTML, /Waiting for Authorized Staff approval/);
      assert.doesNotMatch(elements.evalArea.innerHTML, /data-action="Approved"/);
    }
  }
  for (const role of ["student", "admin", "super_admin"]) {
    vm.runInContext(`currentUser = {role: "${role}"}`, context);
    context.showEvaluation({ status: "Submitted" });
    assert.doesNotMatch(elements.evalArea.innerHTML, /data-action="start"/);
  }
});

test("evaluatorFilter displays current role titles and filters by stored role IDs", () => {
  const { context, elements, createdHtml } = makeHarness(
    () => true,
    () => ({ trimester: "2nd Trimester" })
  );

  assert.match(createdHtml.evaluatorFilter, /<option value="">Evaluated by: All<\/option>/);
  assert.match(createdHtml.evaluatorFilter, /<option value="staff">Authorized Staff<\/option>/);
  assert.match(createdHtml.evaluatorFilter, /<option value="admin">Admin<\/option>/);
  assert.match(createdHtml.evaluatorFilter, /<option value="president">Director of Academic Services<\/option>/);
  assert.match(createdHtml.evaluatorFilter, /<option value="executive_president">University President<\/option>/);

  vm.runInContext(
    `allApps = [
      { id: "1", code: "APP-00001", termId: "term-2", term: "2nd Trimester", studentName: "Student One", studentId: "2400001", program: "BS IT", yearLevel: "1st Year", scholarshipType: "Academic Scholarship", dateSubmitted: "2026-11-18", discountPercent: 50, status: "Approved", evaluators: ["Staff One"], evaluatorRoles: ["staff"], archived: false },
      { id: "2", code: "APP-00006", termId: "term-2", term: "2nd Trimester", studentName: "Arman Clark Untalan", studentId: "2400779", program: "BS IT", yearLevel: "3rd Year", scholarshipType: "Academic Scholarship", dateSubmitted: "2026-11-19", discountPercent: 50, status: "Approved", evaluators: ["System Admin"], evaluatorRoles: ["admin"], archived: false }
    ];`,
    context
  );

  context.showApplications();
  assert.equal(elements.filterCount.textContent, "Showing 2 of 2 applications");

  elements.evaluatorFilter.value = "staff";
  context.showApplications();
  assert.equal(elements.filterCount.textContent, "Showing 1 of 2 applications");
  assert.match(elements.applicationRows.innerHTML, /APP-00001/);
  assert.doesNotMatch(elements.applicationRows.innerHTML, /APP-00006/);

  elements.evaluatorFilter.value = "admin";
  context.showApplications();
  assert.equal(elements.filterCount.textContent, "Showing 1 of 2 applications");
  assert.match(elements.applicationRows.innerHTML, /APP-00006/);
  assert.doesNotMatch(elements.applicationRows.innerHTML, /APP-00001/);
});

test("filterCount counts only applications in the selected viewing term unless All terms/years is active", () => {
  let viewingTerm = "term-2";
  const { context, elements } = makeHarness(
    (app) => !viewingTerm || app.termId === viewingTerm,
    () => (viewingTerm === "term-2" ? { id: "term-2", trimester: "2nd Trimester" } : null)
  );

  vm.runInContext(
    `allApps = [
      { id: "1", code: "APP-00001", termId: "term-1", term: "1st Trimester", studentName: "Student One", studentId: "2400001", program: "BS IT", yearLevel: "1st Year", scholarshipType: "Academic Scholarship", dateSubmitted: "2026-09-01", discountPercent: null, status: "Approved", evaluators: ["System Admin"], evaluatorRoles: ["admin"], archived: true },
      { id: "2", code: "APP-00006", termId: "term-2", term: "2nd Trimester", studentName: "Arman Clark Untalan", studentId: "2400779", program: "BS IT", yearLevel: "3rd Year", scholarshipType: "Academic Scholarship", dateSubmitted: "2026-11-19", discountPercent: 50, status: "Approved", evaluators: ["System Admin"], evaluatorRoles: ["admin"], archived: false }
    ];`,
    context
  );

  context.showApplications();
  assert.equal(elements.filterCount.textContent, "Showing 1 of 1 application");

  viewingTerm = "";
  context.showApplications();
  assert.equal(elements.filterCount.textContent, "Showing 2 of 2 applications");
});

test("the Changed after sent to Finance tab filters flagged applications", () => {
  const { context, elements } = makeHarness(
    () => true,
    () => ({ trimester: "2nd Trimester" })
  );

  vm.runInContext(
    `allApps = [
      { id: "1", code: "APP-00001", termId: "term-2", term: "2nd Trimester", studentName: "Student One", studentId: "2400001", program: "BS IT", yearLevel: "1st Year", scholarshipType: "Academic Scholarship", dateSubmitted: "2026-11-18", discountPercent: 50, status: "Under Evaluation", changedAfterFinance: true, evaluators: [], evaluatorRoles: [], archived: false },
      { id: "2", code: "APP-00002", termId: "term-2", term: "2nd Trimester", studentName: "Student Two", studentId: "2400002", program: "BS IT", yearLevel: "1st Year", scholarshipType: "Academic Scholarship", dateSubmitted: "2026-11-19", discountPercent: 50, status: "Under Evaluation", changedAfterFinance: false, evaluators: [], evaluatorRoles: [], archived: false },
      { id: "3", code: "APP-00003", termId: "term-2", term: "2nd Trimester", studentName: "Student Three", studentId: "2400003", program: "BS IT", yearLevel: "1st Year", scholarshipType: "Academic Scholarship", dateSubmitted: "2026-11-19", discountPercent: 50, status: "Sent to Finance", changedAfterFinance: false, evaluators: [], evaluatorRoles: [], archived: false }
    ];
    activeTab = CHANGED_AFTER_FINANCE;`,
    context
  );

  context.showApplications();
  assert.match(elements.applicationRows.innerHTML, /APP-00001/);
  assert.doesNotMatch(elements.applicationRows.innerHTML, /APP-00002/);
  assert.doesNotMatch(elements.applicationRows.innerHTML, /APP-00003/);
  assert.equal(elements.filterCount.textContent, "Showing 1 of 3 applications");

  vm.runInContext('activeTab = "Sent to Finance";', context);
  context.showApplications();
  assert.match(elements.applicationRows.innerHTML, /APP-00003/);
  assert.doesNotMatch(elements.applicationRows.innerHTML, /APP-00001/);
});

function makeCommonContext() {
  const commonSource = readFileSync("PU scholarship system/js/common.js", "utf8");
  const commonContext = vm.createContext({
    document: { addEventListener() {}, getElementById: () => null, querySelectorAll: () => [], documentElement: {} },
    window: { addEventListener() {} },
    sessionStorage: { getItem: () => null, removeItem() {} },
    MutationObserver: class { observe() {} },
  });
  vm.runInContext(dataSource, commonContext);
  vm.runInContext(commonSource, commonContext);
  return commonContext;
}

test("saved approval statuses and audit details display current titles without rewriting remarks", () => {
  const context = makeCommonContext();
  context.runPage = () => {};
  vm.runInContext(readFileSync("PU scholarship system/js/audit-log.js", "utf8"), context);
  for (const [role, original, title] of [
    ["president", "President", "Director of Academic Services"],
    ["executive_president", "Executive President", "University President"],
  ]) {
    const status = `Approved by ${original}`;
    assert.ok(context.statusBadge(status).includes(`>Approved by ${title}</span>`));
    assert.ok(context.roleBadge(role).includes(`>${title}</span>`));
    const details = { stage: role, position: original, status, remarks: `Spoke with the ${original}.` };
    const html = context.detailsHtml(details, "application_approved");
    assert.ok(html.includes(`>${title}</span>`));
    assert.ok(html.includes(`>Approved by ${title}</span>`));
    assert.ok(!html.includes(`>${role}</span>`) && !html.includes(`>${original}</span>`));
    assert.ok(html.includes(details.remarks));
    assert.equal(details.position, original);
  }
});

test("Changed after sent to Finance status badges wrap in status-badges without left-margin offset", () => {
  const commonContext = makeCommonContext();
  const flaggedHtml = commonContext.applicationStatusBadges({
    status: "Endorsed by Staff",
    changedAfterFinance: true,
  });
  assert.equal(
    flaggedHtml,
    '<div class="status-badges"><span class="badge badge-endorsed-by-staff">Endorsed by Staff</span><span class="badge badge-changed-after-finance" title="Edited after Finance already received this scholar, so the three approvals run again.">Changed after sent to Finance</span></div>'
  );

  const normalHtml = commonContext.applicationStatusBadges({
    status: "Approved",
    changedAfterFinance: false,
  });
  assert.equal(
    normalHtml,
    '<div class="status-badges"><span class="badge badge-approved">Approved</span></div>'
  );

  for (const cssPath of [
    "PU scholarship system/css/staff-applications.css",
    "PU scholarship system/css/my-applications.css",
    "PU scholarship system/css/audit-log.css",
    "PU scholarship system/css/staff-accounts.css",
    "PU scholarship system/css/student-dashboard.css",
  ]) {
    const css = readFileSync(cssPath, "utf8");
    const rule = css.match(/\.badge-changed-after-finance\s*\{[^}]*\}/);
    assert.ok(rule, `Expected .badge-changed-after-finance rule in ${cssPath}`);
    assert.doesNotMatch(rule[0], /margin-left:/, `${cssPath} should not offset .badge-changed-after-finance`);
  }

  const sidebarCss = readFileSync("PU scholarship system/css/sidebar.css", "utf8");
  assert.match(sidebarCss, /\.status-badges\s*\{[^}]*flex-direction:\s*column;[^}]*gap:\s*6px;/s);
  assert.match(sidebarCss, /@media\s*\(max-width:\s*600px\)\s*\{[^}]*\.badge\s*\{[^}]*white-space:\s*normal;/s);

  const staffCss = readFileSync("PU scholarship system/css/staff-applications.css", "utf8");
  assert.match(staffCss, /table\.data-table td\[data-label="Status"\]\s+\.status-badges/);

  const appViewSource = readFileSync("PU scholarship system/js/application-view.js", "utf8");
  assert.match(appViewSource, /<dd class="finance-flag-dd"><span class="badge badge-changed-after-finance">/);
});

