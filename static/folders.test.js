const test = require("node:test");
const assert = require("node:assert/strict");

global.localStorage = (() => {
  let store = {};
  return {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
    __reset: () => { store = {}; },
  };
})();

const { groupRequestsByFolder, countRequestsInGroup, isFolderCollapsed, setFolderCollapsed } = require("./folders.js");

test("groupRequestsByFolder: partitions requests into folder buckets plus uncategorized, preserving folder order", () => {
  const collection = {
    folders: [{ id: "f1", name: "Auth" }, { id: "f2", name: "Loans" }],
    requests: [
      { name: "A", folderId: "f1" },
      { name: "B", folderId: "f2" },
      { name: "C" },
      { name: "D", folderId: "f1" },
    ],
  };
  const { folderGroups, uncategorized } = groupRequestsByFolder(collection);
  assert.deepEqual(folderGroups.map((g) => g.folder.id), ["f1", "f2"]);
  assert.deepEqual(folderGroups[0].requests.map((r) => r.name), ["A", "D"]);
  assert.deepEqual(folderGroups[1].requests.map((r) => r.name), ["B"]);
  assert.deepEqual(uncategorized.map((r) => r.name), ["C"]);
});

test("groupRequestsByFolder: a folderId with no matching folder falls back to uncategorized", () => {
  const collection = { folders: [], requests: [{ name: "A", folderId: "ghost" }] };
  const { folderGroups, uncategorized } = groupRequestsByFolder(collection);
  assert.deepEqual(folderGroups, []);
  assert.deepEqual(uncategorized.map((r) => r.name), ["A"]);
});

test("groupRequestsByFolder: an empty folder still gets a group with no requests", () => {
  const collection = { folders: [{ id: "f1", name: "Empty" }], requests: [] };
  const { folderGroups, uncategorized } = groupRequestsByFolder(collection);
  assert.deepEqual(folderGroups.map((g) => g.folder.id), ["f1"]);
  assert.deepEqual(folderGroups[0].requests, []);
  assert.deepEqual(uncategorized, []);
});

test("groupRequestsByFolder: tolerates a collection with no folders/requests keys at all", () => {
  const { folderGroups, uncategorized } = groupRequestsByFolder({});
  assert.deepEqual(folderGroups, []);
  assert.deepEqual(uncategorized, []);
});

test("groupRequestsByFolder: existing single-level collections render identically to before (root groups just gain an empty children array)", () => {
  const collection = {
    folders: [{ id: "f1", name: "Auth" }, { id: "f2", name: "Loans" }],
    requests: [{ name: "A", folderId: "f1" }],
  };
  const { folderGroups } = groupRequestsByFolder(collection);
  assert.deepEqual(folderGroups, [
    { folder: { id: "f1", name: "Auth" }, requests: [{ name: "A", folderId: "f1" }], children: [] },
    { folder: { id: "f2", name: "Loans" }, requests: [], children: [] },
  ]);
});

test("groupRequestsByFolder: root folders omit parentFolderId entirely (the backend's storage convention), not set it to null", () => {
  const collection = { folders: [{ id: "f1", name: "Root" }], requests: [] };
  const { folderGroups } = groupRequestsByFolder(collection);
  assert.equal(folderGroups.length, 1);
  assert.equal("parentFolderId" in folderGroups[0].folder, false);
});

test("groupRequestsByFolder: builds a nested tree keyed by parentFolderId, three levels deep", () => {
  const collection = {
    folders: [
      { id: "root", name: "Root" },
      { id: "child", name: "Child", parentFolderId: "root" },
      { id: "grandchild", name: "Grandchild", parentFolderId: "child" },
    ],
    requests: [],
  };
  const { folderGroups } = groupRequestsByFolder(collection);
  assert.equal(folderGroups.length, 1);
  assert.equal(folderGroups[0].folder.id, "root");
  assert.equal(folderGroups[0].children.length, 1);
  assert.equal(folderGroups[0].children[0].folder.id, "child");
  assert.equal(folderGroups[0].children[0].children.length, 1);
  assert.equal(folderGroups[0].children[0].children[0].folder.id, "grandchild");
  assert.deepEqual(folderGroups[0].children[0].children[0].children, []);
});

test("groupRequestsByFolder: a request under a grandchild folder appears in that leaf group, not any ancestor", () => {
  const collection = {
    folders: [
      { id: "root", name: "Root" },
      { id: "child", name: "Child", parentFolderId: "root" },
      { id: "grandchild", name: "Grandchild", parentFolderId: "child" },
    ],
    requests: [{ name: "Deep", folderId: "grandchild" }],
  };
  const { folderGroups } = groupRequestsByFolder(collection);
  assert.deepEqual(folderGroups[0].requests, []);
  assert.deepEqual(folderGroups[0].children[0].requests, []);
  assert.deepEqual(folderGroups[0].children[0].children[0].requests.map((r) => r.name), ["Deep"]);
});

test("groupRequestsByFolder: sibling order within a parent follows collection.folders order", () => {
  const collection = {
    folders: [
      { id: "root", name: "Root" },
      { id: "b", name: "B", parentFolderId: "root" },
      { id: "a", name: "A", parentFolderId: "root" },
    ],
    requests: [],
  };
  const { folderGroups } = groupRequestsByFolder(collection);
  assert.deepEqual(folderGroups[0].children.map((g) => g.folder.id), ["b", "a"]);
});

test("groupRequestsByFolder: a parentFolderId with no matching folder self-heals to root, same convention as an orphan request folderId", () => {
  const collection = { folders: [{ id: "f1", name: "Orphan", parentFolderId: "ghost" }], requests: [] };
  const { folderGroups } = groupRequestsByFolder(collection);
  assert.deepEqual(folderGroups.map((g) => g.folder.id), ["f1"]);
});

test("countRequestsInGroup: a leaf folder's count is just its own direct requests", () => {
  const group = { folder: { id: "f1" }, requests: [{ name: "A" }, { name: "B" }], children: [] };
  assert.equal(countRequestsInGroup(group), 2);
});

test("countRequestsInGroup: a folder with no direct requests rolls up its children's counts, not zero", () => {
  const collection = {
    folders: [
      { id: "root", name: "Root" },
      { id: "child", name: "Child", parentFolderId: "root" },
      { id: "grandchild", name: "Grandchild", parentFolderId: "child" },
    ],
    requests: [
      { name: "Deep1", folderId: "grandchild" },
      { name: "Deep2", folderId: "grandchild" },
    ],
  };
  const { folderGroups } = groupRequestsByFolder(collection);
  assert.equal(countRequestsInGroup(folderGroups[0]), 2);
  assert.equal(countRequestsInGroup(folderGroups[0].children[0]), 2);
  assert.equal(countRequestsInGroup(folderGroups[0].children[0].children[0]), 2);
});

test("countRequestsInGroup: sums direct requests plus all descendant requests across multiple siblings", () => {
  const collection = {
    folders: [
      { id: "root", name: "Root" },
      { id: "a", name: "A", parentFolderId: "root" },
      { id: "b", name: "B", parentFolderId: "root" },
    ],
    requests: [
      { name: "R1", folderId: "root" },
      { name: "R2", folderId: "a" },
      { name: "R3", folderId: "b" },
      { name: "R4", folderId: "b" },
    ],
  };
  const { folderGroups } = groupRequestsByFolder(collection);
  assert.equal(countRequestsInGroup(folderGroups[0]), 4);
});

test("isFolderCollapsed: defaults to true (collapsed) when nothing stored", () => {
  global.localStorage.__reset();
  assert.equal(isFolderCollapsed("c", "f1"), true);
});

test("isFolderCollapsed: an old-scheme explicit \"true\" value stays collapsed (backward compat, no migration needed)", () => {
  global.localStorage.__reset();
  localStorage.setItem("iris.folderCollapsed.c.f1", "true");
  assert.equal(isFolderCollapsed("c", "f1"), true);
});

test("isFolderCollapsed: a folder explicitly expanded by the user stays expanded across a reload", () => {
  global.localStorage.__reset();
  setFolderCollapsed("c", "f1", false);
  assert.equal(isFolderCollapsed("c", "f1"), false);
});

test("isFolderCollapsed/setFolderCollapsed: round-trip through localStorage", () => {
  global.localStorage.__reset();
  setFolderCollapsed("c", "f1", true);
  assert.equal(isFolderCollapsed("c", "f1"), true);
  setFolderCollapsed("c", "f1", false);
  assert.equal(isFolderCollapsed("c", "f1"), false);
  setFolderCollapsed("c", "f1", true);
  assert.equal(isFolderCollapsed("c", "f1"), true);
});

test("isFolderCollapsed: is keyed per collection AND folder, not just folder id", () => {
  global.localStorage.__reset();
  setFolderCollapsed("c1", "f1", false);
  assert.equal(isFolderCollapsed("c2", "f1"), true);
});
