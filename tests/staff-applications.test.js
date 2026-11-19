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
        if (match) elements[match[1]] = makeSelect(match[1]);
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
  });
  vm.runInContext(source, context);
  context.initExtraFilters();
  return { context, elements };
}

test("evaluatorFilter includes active staffEvaluators even with zero evaluated apps in scope", () => {
  const { context, elements } = makeHarness(
    () => true,
    () => ({ trimester: "2nd Trimester" })
  );

  vm.runInContext(
    `staffEvaluators = ["Authorized Staff", "System Admin"];
     allApps = [{ program: "BS Information Technology", status: "Approved", evaluators: ["System Admin"] }];`,
    context
  );
  context.refreshFilterOptions();
  assert.match(elements.evaluatorFilter.innerHTML, /Authorized Staff/);
  assert.match(elements.evaluatorFilter.innerHTML, /System Admin/);
  assert.doesNotMatch(elements.evaluatorFilter.innerHTML, /Arman Clark Untalan/);

  elements.evaluatorFilter.value = "System Admin";
  vm.runInContext(
    `allApps = [...allApps, { program: "BS Information Technology", status: "Approved", evaluators: ["Former Staff", "System Admin"] }];`,
    context
  );
  context.refreshFilterOptions();
  assert.match(elements.evaluatorFilter.innerHTML, /Authorized Staff/);
  assert.match(elements.evaluatorFilter.innerHTML, /Former Staff/);
  assert.match(elements.evaluatorFilter.innerHTML, /System Admin/);
  assert.equal(elements.evaluatorFilter.value, "System Admin");
});

test("filterCount counts only applications in the selected viewing term unless All terms/years is active", () => {
  let viewingTerm = "term-2";
  const { context, elements } = makeHarness(
    (app) => !viewingTerm || app.termId === viewingTerm,
    () => (viewingTerm === "term-2" ? { id: "term-2", trimester: "2nd Trimester" } : null)
  );

  vm.runInContext(
    `allApps = [
      { id: "1", code: "APP-00001", termId: "term-1", term: "1st Trimester", studentName: "Student One", studentId: "2400001", program: "BS IT", yearLevel: "1st Year", scholarshipType: "Academic Scholarship", dateSubmitted: "2026-09-01", discountPercent: null, status: "Approved", evaluators: ["System Admin"], archived: true },
      { id: "2", code: "APP-00006", termId: "term-2", term: "2nd Trimester", studentName: "Arman Clark Untalan", studentId: "2400779", program: "BS IT", yearLevel: "3rd Year", scholarshipType: "Academic Scholarship", dateSubmitted: "2026-11-19", discountPercent: 50, status: "Approved", evaluators: ["System Admin"], archived: false }
    ];`,
    context
  );

  context.showApplications();
  assert.equal(elements.filterCount.textContent, "Showing 1 of 1 application");

  viewingTerm = "";
  context.showApplications();
  assert.equal(elements.filterCount.textContent, "Showing 2 of 2 applications");
});
