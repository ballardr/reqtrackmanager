import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { buildFolder } from "./architectureFixtures";
import {
  buildFolderTree, folderSelectNodes, folderSubtreeIds, inChosenFolder, inChosenOwnerFolders, ownerFolderNodes, treeFromPaths,
} from "./folderTree";

const FOLDERS = [
  buildFolder({ id: "sw", name: "Software", path: "Software" }),
  buildFolder({ id: "mod", name: "Modules", path: "Software/Modules", parent_id: "sw" }),
  buildFolder({ id: "api", name: "Api", path: "Software/Modules/Api", parent_id: "mod" }),
  buildFolder({ id: "hw", name: "Hardware", path: "Hardware" }),
];

function Host() {
  return <p>Checks the folder tree helpers.</p>;
}

const meta: Meta<typeof Host> = { title: "Modules/Architecture/FolderTree", component: Host };
export default meta;
type Story = StoryObj<typeof Host>;

export const BuildsTheTreeAndLeavesOutAFoldersOwnSubtreeWhenMoving: Story = {
  play: async () => {
    const tree = buildFolderTree(FOLDERS);
    await expect(tree.map((n) => n.folder.name)).toEqual(["Software", "Hardware"]);
    await expect(tree[0].children[0].children[0].folder.name).toBe("Api");
    await expect([...folderSubtreeIds(FOLDERS, "sw")].sort()).toEqual(["api", "mod", "sw"]);
    const choices = folderSelectNodes(FOLDERS, "mod");
    await expect(choices.map((n) => n.id)).toEqual(["sw", "hw"]);
    await expect(choices[0].children).toEqual([]);
    await expect(folderSelectNodes(FOLDERS)[0].children[0].pathLabel).toBe("Software/Modules");
  },
};

export const MatchesAPathExactlyOrWithItsSubfoldersIgnoringCase: Story = {
  play: async () => {
    await expect(inChosenFolder("Software/Modules", "software", true)).toBe(true);
    await expect(inChosenFolder("Software/Modules", "software", false)).toBe(false);
    await expect(inChosenFolder("Software", "software", false)).toBe(true);
    await expect(inChosenFolder("Software2/Modules", "software", true)).toBe(false);
    await expect(inChosenFolder(null, "software", true)).toBe(false);
    await expect(inChosenFolder(null, "", true)).toBe(true);
  },
};

export const DrawsOnlyTheFoldersOnTheWayToAReadableRecord: Story = {
  play: async () => {
    const tree = treeFromPaths(["Platform/Services", "Platform/Services", null, "Boards"]);
    await expect(tree.map((n) => n.path)).toEqual(["Boards", "Platform"]);
    await expect(tree[1].children.map((n) => n.path)).toEqual(["Platform/Services"]);

    const nodes = ownerFolderNodes([
      { ownerKey: "project:p2", ownerLabel: "Another project", folderPath: "Infra/Net" },
      { ownerKey: "own", ownerLabel: "This project", folderPath: "Software" },
      { ownerKey: "own", ownerLabel: "This project", folderPath: null },
    ], "own");
    await expect(nodes.map((n) => n.label)).toEqual(["This project", "Another project"]);
    await expect(nodes[1].children[0].children[0].pathLabel).toBe("Infra/Net");
    await expect(nodes[1].children[0].children).toHaveLength(1);

    await expect(inChosenOwnerFolders([], "own", null)).toBe(true);
    await expect(inChosenOwnerFolders(["owner:own"], "own", null)).toBe(true);
    await expect(inChosenOwnerFolders(["owner:own"], "project:p2", "Infra")).toBe(false);
    await expect(inChosenOwnerFolders(["folder:project:p2|Infra"], "project:p2", "Infra/Net")).toBe(true);
    await expect(inChosenOwnerFolders(["folder:project:p2|Infra"], "own", "Infra/Net")).toBe(false);
  },
};
