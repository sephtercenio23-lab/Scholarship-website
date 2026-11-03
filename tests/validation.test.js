const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync("PU scholarship system/js/validation.js", "utf8");
const context = vm.createContext({});
vm.runInContext(source + `
  globalThis.results = {
    years: ["2026-2027", "2026/2027", "2026–2027"].map(checkAcademicYear),
    normalized: normalizeAcademicYear("2026–2027"),
    invalidYear: checkAcademicYear("2026-2028"),
    emptyFile: validateFile({ name: "grades.pdf", size: 0 }),
    validFile: validateFile({ name: "grades.pdf", size: 12 }),
    oversizedFile: validateFile({ name: "grades.pdf", size: 6 * 1024 * 1024 }),
    badFile: validateFile({ name: "grades.exe", size: 12 }),
    password: validatePassword("Validpass1!"),
  };
`, context);
assert(context.results.years.every((item) => item.valid));
assert.strictEqual(context.results.normalized, "2026–2027");
assert.strictEqual(context.results.invalidYear.valid, false);
assert.strictEqual(context.results.emptyFile.valid, false);
assert.strictEqual(context.results.validFile.valid, true);
assert.strictEqual(context.results.oversizedFile.valid, false);
assert.strictEqual(context.results.badFile.valid, false);
assert.strictEqual(context.results.password.valid, true);
console.log("Browser validation regression checks passed");
