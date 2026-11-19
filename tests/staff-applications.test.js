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
    listeners: {},
    addEventListener(event, fn) {
      this.listeners[event] = fn;
    },
  };
}

test("evaluatorFilter refreshes from scoped applications evaluators", () => {
  const elements = {
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
    escapeHtml: (value) =>
      String(value).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch])),
    matchesViewing: () => true,
    selectedViewingTerm: () => ({ trimester: "2nd Trimester" }),
    dutyKey: () => "Not Started",
    showApplications: () => {},
  });
  vm.runInContext(source, context);

  vm.runInContext(
    `allApps = [{ program: "BS Information Technology", status: "Approved", evaluators: ["System Admin"] }];`,
    context
  );
  context.initExtraFilters();
  context.refreshFilterOptions();
  assert.match(elements.evaluatorFilter.innerHTML, /System Admin/);
  assert.doesNotMatch(elements.evaluatorFilter.innerHTML, /Arman Clark Untalan/);

  elements.evaluatorFilter.value = "System Admin";
  vm.runInContext(
    `allApps = [...allApps, { program: "BS Information Technology", status: "Approved", evaluators: ["Authorized Staff", "System Admin"] }];`,
    context
  );
  context.refreshFilterOptions();
  assert.match(elements.evaluatorFilter.innerHTML, /Authorized Staff/);
  assert.match(elements.evaluatorFilter.innerHTML, /System Admin/);
  assert.equal(elements.evaluatorFilter.value, "System Admin");
});
