const test = require("node:test");
const assert = require("node:assert/strict");

const fakeElements = {};
global.$ = (id) => fakeElements[id] || (fakeElements[id] = { value: "" });
global.document = { addEventListener: () => {} };

const { blurActiveElementWithin, discardActiveElementEditWithin } = require("./env-modal-footer.js");

// Stands in for a real .env-var-name/.env-var-value <input> — matches(...)
// returns true for exactly the selector isCommittableEnvField checks.
function fakeCommittableField(value, defaultValue) {
  let blurred = false;
  return {
    value, defaultValue,
    matches: (selector) => selector === ".env-var-name, .env-var-value",
    blur: () => { blurred = true; },
    wasBlurred: () => blurred,
  };
}

// The env modal's Save button doesn't have its own persistence path — fields
// already save on blur/change. Its job is to commit whatever field the user
// is still mid-edit in (so clicking Save instead of clicking away also
// works) without blurring something outside the modal that has nothing to
// do with it.
test("blurActiveElementWithin: blurs the active element when it is inside the container", () => {
  const active = fakeCommittableField("v", "v");
  const container = { contains: (el) => el === active };
  document.activeElement = active;
  assert.equal(blurActiveElementWithin(container), true);
  assert.equal(active.wasBlurred(), true);
});

test("blurActiveElementWithin: leaves focus alone when the active element is outside the container", () => {
  const active = fakeCommittableField("v", "v");
  const container = { contains: () => false };
  document.activeElement = active;
  assert.equal(blurActiveElementWithin(container), false);
  assert.equal(active.wasBlurred(), false);
});

test("blurActiveElementWithin: does nothing when nothing is focused", () => {
  document.activeElement = null;
  assert.equal(blurActiveElementWithin({ contains: () => true }), false);
});

// Regression: the Bulk Edit textarea (and the enabled checkbox, and the
// Save/Cancel buttons themselves) are all reachable as document.activeElement
// while inside #envModal, but none of them are a row's name/value input —
// blurring or discarding through them must be a no-op.
test("blurActiveElementWithin: ignores an active element that isn't a row name/value input", () => {
  let blurred = false;
  const active = { value: "some JSON", matches: () => false, blur: () => { blurred = true; } };
  document.activeElement = active;
  assert.equal(blurActiveElementWithin({ contains: () => true }), false);
  assert.equal(blurred, false);
});

// Cancel must discard an in-progress, not-yet-committed edit rather than
// saving it — resetting the field back to its last-rendered (i.e.
// last-saved) value before blurring means the native blur→change→save path
// sees no diff and never fires, unlike Save's plain blur.
test("discardActiveElementEditWithin: reverts the active field to its last-rendered value and blurs it", () => {
  const active = fakeCommittableField("typed-but-unsaved", "last-saved");
  const container = { contains: (el) => el === active };
  document.activeElement = active;
  assert.equal(discardActiveElementEditWithin(container), true);
  assert.equal(active.value, "last-saved");
  assert.equal(active.wasBlurred(), true);
});

test("discardActiveElementEditWithin: leaves focus alone when the active element is outside the container", () => {
  const active = { value: "typed", defaultValue: "orig", matches: () => true, blur: () => { throw new Error("must not blur"); } };
  document.activeElement = active;
  assert.equal(discardActiveElementEditWithin({ contains: () => false }), false);
  assert.equal(active.value, "typed");
});

// Regression (critical, caught by independent review): the Bulk Edit
// textarea is populated by `bulkArea.value = json` — a property assignment
// that never touches defaultValue, so defaultValue is permanently "". Before
// this scoping, clicking Cancel while that textarea was focused reset it to
// "" and blurred it, destroying the pasted JSON with no way to recover it —
// re-opening the modal and clicking "Done" would then wipe every variable.
test("discardActiveElementEditWithin: never touches the Bulk Edit textarea, even though it's inside the modal", () => {
  const bulkTextarea = { value: '{"url": "https://real-value"}', defaultValue: "", matches: () => false, blur: () => { throw new Error("must not blur"); } };
  document.activeElement = bulkTextarea;
  assert.equal(discardActiveElementEditWithin({ contains: () => true }), false);
  assert.equal(bulkTextarea.value, '{"url": "https://real-value"}');
});
