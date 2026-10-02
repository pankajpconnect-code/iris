const test = require("node:test");
const assert = require("node:assert/strict");

const { listAllFolderGroups, listFolderGroupsExcludingSubtree } = require("./sidebar-context-menu.js");

// Same nested shape groupRequestsByFolder (folders.js) builds: root -> child -> grandchild.
function threeLevelTree() {
  return [
    {
      folder: { id: "root", name: "Root" },
      requests: [],
      children: [
        {
          folder: { id: "child", name: "Child" },
          requests: [],
          children: [
            { folder: { id: "grandchild", name: "Grandchild" }, requests: [], children: [] },
          ],
        },
      ],
    },
  ];
}

test("listAllFolderGroups: lists every folder in parent-before-children order with its depth", () => {
  const entries = listAllFolderGroups(threeLevelTree(), 0, []);
  assert.deepEqual(
    entries.map((e) => [e.folder.id, e.depth]),
    [["root", 0], ["child", 1], ["grandchild", 2]]
  );
});

test("listFolderGroupsExcludingSubtree: omits the target folder and stops descending into its children", () => {
  const entries = listFolderGroupsExcludingSubtree(threeLevelTree(), 0, "child", []);
  assert.deepEqual(entries.map((e) => e.folder.id), ["root"]);
});

test("listFolderGroupsExcludingSubtree: excluding the root omits the whole tree", () => {
  const entries = listFolderGroupsExcludingSubtree(threeLevelTree(), 0, "root", []);
  assert.deepEqual(entries, []);
});

test("listFolderGroupsExcludingSubtree: excluding a non-matching id leaves the full tree intact", () => {
  const entries = listFolderGroupsExcludingSubtree(threeLevelTree(), 0, "unrelated", []);
  assert.deepEqual(entries.map((e) => e.folder.id), ["root", "child", "grandchild"]);
});
