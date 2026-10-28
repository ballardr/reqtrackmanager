import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { buildBlockCatalogue, buildOutlineTree } from "../testing/reportLayoutFixtures";
import {
  duplicateNode, formatPath, getAt, indentNode, indentTarget, insertNode, moveNode, namesInScope, nodeAt, outdentNode, owningNode,
  parsePath, removeNode, setAt, stableJson, summarise,
} from "./reportLayoutTree";

/** The pure helpers behind the block outline, exercised as plain functions (the stories render nothing). */
const meta: Meta = { title: "Utils/reportLayoutTree", render: () => <p>Pure helpers; see the interactions.</p> };
export default meta;

type Story = StoryObj;

const types = buildBlockCatalogue().blocks;
const kinds = (tree: Record<string, unknown>) => (tree.nodes as { type: string }[]).map((n) => n.type);

export const PathsRoundTripThroughSegments: Story = {
  play: async () => {
    const path = "nodes[1].children[0].columns[2].field";
    await expect(parsePath(path)).toEqual(["nodes", 1, "children", 0, "columns", 2, "field"]);
    await expect(formatPath(parsePath(path))).toBe(path);
    await expect(parsePath("")).toEqual([]);
  },
};

export const AProblemBelongsToTheInnermostBlock: Story = {
  play: async () => {
    await expect(owningNode("nodes[1].children[0].level")).toEqual({ addr: ["nodes", 1, "children", 0], rest: ["level"] });
    // A column's index is not a block: the problem is the table's, about its `columns`.
    await expect(owningNode("nodes[1].children[1].columns[0].field")).toEqual({ addr: ["nodes", 1, "children", 1], rest: ["columns", 0, "field"] });
    await expect(owningNode("nodes[0]")).toEqual({ addr: ["nodes", 0], rest: [] });
    await expect(owningNode("orientation")).toBeNull();
    await expect(owningNode("")).toBeNull();
  },
};

export const SettingAValueCopiesAndNeverMutates: Story = {
  play: async () => {
    const tree = buildOutlineTree();
    const before = stableJson(tree);
    const next = setAt(tree, ["nodes", 0, "text"], "Changed");
    await expect(getAt(next, ["nodes", 0, "text"])).toBe("Changed");
    await expect(stableJson(tree)).toBe(before);
    // Undefined removes the key; a missing branch is created.
    await expect(nodeAt(setAt(next, ["nodes", 0, "level"], undefined), ["nodes", 0])).not.toHaveProperty("level");
    await expect(getAt(setAt({}, ["a", "b", 0], "x"), ["a", "b", 0])).toBe("x");
  },
};

export const InsertingAndRemovingKeepOrder: Story = {
  play: async () => {
    const tree = buildOutlineTree();
    const added = insertNode(tree, ["nodes"], 1, { type: "page_break" });
    await expect(kinds(added)).toEqual(["heading", "page_break", "each"]);
    await expect(kinds(removeNode(added, ["nodes", 1]))).toEqual(["heading", "each"]);
    await expect(kinds(tree)).toEqual(["heading", "each"]);
  },
};

export const MovingSwapsNeighboursAndStopsAtTheEnds: Story = {
  play: async () => {
    const tree = buildOutlineTree();
    const down = moveNode(tree, ["nodes", 0], 1);
    await expect(kinds(down!.tree)).toEqual(["each", "heading"]);
    await expect(down!.addr).toEqual(["nodes", 1]);
    await expect(moveNode(tree, ["nodes", 0], -1)).toBeNull();
    await expect(moveNode(tree, ["nodes", 1], 1)).toBeNull();
  },
};

export const IndentingNestsIntoTheBlockAboveIfItHoldsChildren: Story = {
  play: async () => {
    const tree = insertNode(buildOutlineTree(), ["nodes"], 1, { type: "heading", text: "Later" });
    await expect(kinds(tree)).toEqual(["heading", "heading", "each"]);
    // The first block has nothing above; a heading above cannot hold children.
    await expect(indentTarget(tree, ["nodes", 0], types)).toBeNull();
    await expect(indentTarget(tree, ["nodes", 1], types)).toBeNull();
    // The each (index 2) follows a heading, so it cannot go in; a block after the each can.
    const withTail = insertNode(tree, ["nodes"], 3, { type: "text", text: "Tail" });
    const nested = indentNode(withTail, ["nodes", 3], types)!;
    await expect(nested.addr).toEqual(["nodes", 2, "children", 2]);
    await expect(kinds(nested.tree)).toEqual(["heading", "heading", "each"]);
    await expect(nodeAt(nested.tree, nested.addr)).toMatchObject({ type: "text", text: "Tail" });
  },
};

export const OutdentingPlacesTheBlockAfterItsParent: Story = {
  play: async () => {
    const tree = buildOutlineTree();
    const out = outdentNode(tree, ["nodes", 1, "children", 0])!;
    await expect(out.addr).toEqual(["nodes", 2]);
    await expect(kinds(out.tree)).toEqual(["heading", "each", "heading"]);
    await expect((nodeAt(out.tree, ["nodes", 1])!.children as unknown[]).length).toBe(1);
    await expect(outdentNode(tree, ["nodes", 0])).toBeNull();
  },
};

export const DuplicatesShareNothingWithTheOriginal: Story = {
  play: async () => {
    const tree = buildOutlineTree();
    const copy = duplicateNode(tree, ["nodes", 1])!;
    await expect(copy.addr).toEqual(["nodes", 2]);
    const edited = setAt(copy.tree, ["nodes", 2, "children", 0, "text"], "Only the copy");
    await expect(getAt(edited, ["nodes", 1, "children", 0, "text"])).toBe("{{req.code}} {{req.title}}");
  },
};

export const ScopeIsWhatTheEnclosingBlocksProvide: Story = {
  play: async () => {
    const tree = buildOutlineTree();
    await expect(namesInScope(tree, ["nodes", 1], types)).toEqual([]);
    await expect(namesInScope(tree, ["nodes", 1, "children", 1], types)).toEqual([{ name: "req", kind: "record", recordType: "requirement" }]);
    // A group's members: `each` over a group takes the group's record type.
    const grouped = {
      nodes: [{ type: "group", source: { record_type: "requirement" }, by: "status", children: [{ type: "each", source: { group: "group" }, as: "r", children: [{ type: "text", text: "x" }] }] }],
    };
    await expect(namesInScope(grouped, ["nodes", 0, "children", 0, "children", 0], types)).toEqual([
      { name: "group", kind: "group", recordType: "requirement" },
      { name: "r", kind: "record", recordType: "requirement" },
    ]);
  },
};

export const ASummaryNamesTheBlock: Story = {
  play: async () => {
    await expect(summarise({ type: "heading", text: "  Many   words  " })).toBe("Many words");
    await expect(summarise({ type: "each", source: { record_type: "requirement" } })).toBe("requirement");
    await expect(summarise({ type: "text", text: "x".repeat(100) }, 10)).toBe("xxxxxxxxx…");
    await expect(summarise({ type: "page_break" })).toBe("");
  },
};

export const StableJsonIgnoresKeyOrder: Story = {
  play: async () => {
    await expect(stableJson({ b: 1, a: [2, { d: 1, c: 2 }] })).toBe(stableJson({ a: [2, { c: 2, d: 1 }], b: 1 }));
    await expect(stableJson({ a: 1 })).not.toBe(stableJson({ a: 2 }));
  },
};
