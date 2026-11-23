const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const test = require("node:test");
const vm = require("node:vm");

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
    isApprovedStatus: (status) => ["Approved", "Approved by Executive President", "Exported"].includes(status),
    isPendingApprovalStatus: (status) => ["Under Evaluation", "Endorsed by Staff", "Approved by President"].includes(status),
  });
  vm.runInContext(source, context);
  context.initExtraFilters();
  return { context, elements, createdHtml };
}

test("evaluatorFilter offers All, Authorized Staff, and Admin and filters applications by role", () => {
  const { context, elements, createdHtml } = makeHarness(
    () => true,
    () => ({ trimester: "2nd Trimester" })
  );

  assert.match(createdHtml.evaluatorFilter, /<option value="">Evaluated by: All<\/option>/);
  assert.match(createdHtml.evaluatorFilter, /<option value="staff">Authorized Staff<\/option>/);
  assert.match(createdHtml.evaluatorFilter, /<option value="admin">Admin<\/option>/);

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
