const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const test = require("node:test");
const vm = require("node:vm");

const source = readFileSync("PU scholarship system/js/application-view.js", "utf8");

test("duty edit ignores duplicate clicks and a review that was replaced during the request", async () => {
  let handleClick;
  let resolveApplication;
  let requests = 0;
  const response = new Promise((resolve) => { resolveApplication = resolve; });
  const work = [];
  const cell = { closest: () => ({}) };
  const edit = {
    disabled: false,
    isConnected: true,
    dataset: { dutyEdit: "app-id" },
    closest: () => edit.isConnected ? cell : null,
  };
  const context = vm.createContext({
    document: { addEventListener: (event, listener) => { handleClick = listener; } },
    getApplicationById: () => {
      requests++;
      return response;
    },
    runPage: (fn) => { work.push(fn()); },
  });
  vm.runInContext(source, context);

  const event = { target: { closest: (selector) => selector === "[data-duty-edit]" ? edit : null } };
  handleClick(event);
  handleClick(event);
  edit.isConnected = false;
  resolveApplication({ id: "app-id", status: "Approved", dutyHours: 0 });

  await Promise.all(work);
  assert.equal(requests, 1);
});
