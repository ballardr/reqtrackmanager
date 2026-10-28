import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import linkVectors from "../testing/linkVectors.json";
import starters from "../testing/starterLayoutTrees.json";
import { buildBlockCatalogue, buildOutlineTree } from "../testing/reportLayoutFixtures";
import {
  docToTree, DOC, NotRepresentableError, parseMarkdown, sectionsOf, serializeMarkdown, treeToDoc, type DocNode,
} from "./reportLayoutDoc";
import { headingAnchor, linkProblem } from "./reportLayoutProse";
import { stableJson, type Tree } from "./reportLayoutTree";

/** The converter between a layout tree and the document view's nodes, exercised as plain functions. */
const meta: Meta = { title: "Utils/reportLayoutDoc", render: () => <p>Pure converter; see the interactions.</p> };
export default meta;

type Story = StoryObj;

const types = buildBlockCatalogue().blocks;
/** A module's own block type that holds blocks, to show no code here names a block type. */
const withModuleBlock = [...types, {
  type: "panel", label: "Panel", description: "", families: ["document" as const], fields: [], containers: [{ key: "body", label: "Body" }], provides: null,
  template: { type: "panel", body: [] }, described: true,
}];

const roundTrip = (tree: Tree, catalogue = types): Tree => docToTree(treeToDoc(tree, catalogue), tree);
const tree = (...nodes: unknown[]): Tree => ({ schema_version: 1, family: "document", orientation: "portrait", nodes });
const text = (markdown: string) => ({ type: "text", text: markdown });

export const EveryStarterLayoutRoundTripsExactly: Story = {
  play: async () => {
    for (const [key, starter] of Object.entries(starters)) {
      await expect(stableJson(roundTrip(starter as Tree, withModuleBlock)), key).toBe(stableJson(starter));
    }
  },
};

export const TheOutlineFixtureRoundTrips: Story = {
  play: async () => {
    const t = buildOutlineTree();
    await expect(stableJson(roundTrip(t))).toBe(stableJson(t));
  },
};

export const ProseTextBlocksBecomeParagraphsListsAndHeadings: Story = {
  play: async () => {
    const markdown = "# Scope\n\nThe {{project_name}} plan, with \\( x^2 \\).\nA second line.\n\n- first\n- second";
    const doc = treeToDoc(tree(text(markdown)), types);
    const block = doc.content![0];
    await expect(block.type).toBe(DOC.text);
    await expect(block.content!.map((n) => n.type)).toEqual([DOC.mdHeading, DOC.paragraph, DOC.bulletList]);
    await expect(block.content![1].content![0].text).toBe("The {{project_name}} plan, with \\( x^2 \\).\nA second line.");
    await expect(block.content![2].content!.map((i) => i.content![0].content![0].text)).toEqual(["first", "second"]);
    await expect(stableJson(docToTree(doc, tree()))).toBe(stableJson(tree(text(markdown))));
  },
};

export const MarkdownTheReaderWouldNotRewriteIsShownAsProse: Story = {
  play: async () => {
    const canonical = [
      "One paragraph.", "# Title", "- a\n- b", "A\n\nB\n\n- c", "2024 plan", "Cost (approx.) is 3",
      "Some **bold**, *italic*, `code` and ***both*** words.", "**Starts bold** then plain", "1. one\n2. two\n3. three",
      "- **bold item**\n- plain with `code`", "Math \\(a_1 * b_2\\) and {{record.title}} and snake_case", "5 * 3 = 15",
      "Escaped \\*star\\* and \\`tick\\` and back\\\\slash", "See [the spec](https://example.org/s?a=1) now", "[**bold** link](https://e.org) and [*it*](#c)",
      "- [item](#overview)\n- plain", "1. [a](mailto:a@b.co)\n2. b", "[x]({{record.url}}) and [y](https://h.org/{{record.code}})", "Cost [1] is fine and [2]",
      "Literal \\[x\\](y) brackets", "[a](https://e.org) and [b](#c)", "**bold with \\(x^2\\) inside**", "Line one\nline **two**",
    ];
    for (const markdown of canonical) {
      await expect(parseMarkdown(markdown), markdown).not.toBeNull();
      await expect(serializeMarkdown(parseMarkdown(markdown)!), markdown).toBe(markdown);
    }
  },
};

/** Anything the small reader cannot spell back exactly stays a raw-Markdown block, so no text is rewritten. */
export const MarkdownOutsideTheCanonicalSpellingStaysRaw: Story = {
  play: async () => {
    const odd = [
      " leading space", "trailing space ", "two\n\n\nblank lines", "1) ordered", "* star bullet", "+ plus bullet", "> quote", "```\ncode\n```",
      "| a | b |\n|---|---|", "<b>html</b>", "![img](attachment:1)", "# Title #", "##### five", "Line ending with a backslash\\",
      "Setext\n=====", "- item\ncontinued", "-- dashes", "_emphasis_ start", "a  \nb", "",
      "unmatched *star here", "**bold ** with a space", "* * *", "***", "``double`` ticks", "a\\b stray backslash", "1. a\n3. b", "2. starts at two",
      "[bad](javascript:alert(1))", "[a](https://e.org/a b)", "[a](relative)", "[code `x`](https://e.org)", "[nested [x]](https://e.org)", "[empty]()",
      "[unclosed](https://e.org", "*[it](#c)* wrapped", "[**a](https://e.org)**", "# Title with **bold**", "**x**y*", "snake_ _case", "a `unclosed tick", "**\"quoted\"**word",
    ];
    for (const markdown of odd) {
      await expect(parseMarkdown(markdown), JSON.stringify(markdown)).toBeNull();
      if (markdown === "") continue;
      const t = tree(text(markdown));
      const doc = treeToDoc(t, types);
      await expect(doc.content![0].type, markdown).toBe(DOC.raw);
      await expect(stableJson(docToTree(doc, t)), markdown).toBe(stableJson(t));
    }
  },
};

export const HeadingsKeepAnAbsentLevelAbsent: Story = {
  play: async () => {
    const t = tree({ type: "heading", text: "No level" }, { type: "heading", text: "Level", level: 3 });
    const back = roundTrip(t);
    await expect(stableJson(back)).toBe(stableJson(t));
    await expect(back.nodes as unknown[]).toHaveLength(2);
    await expect((back.nodes as Record<string, unknown>[])[0]).not.toHaveProperty("level");
  },
};

export const ContainersKeepEachChildListAndAnAbsentElseAbsent: Story = {
  play: async () => {
    const withElse = { type: "if", when: { module: "risk_management" }, children: [text("Yes")], else_children: [text("No")] };
    const emptyElse = { type: "if", when: { ref: "r.status", op: "eq", value: "x" }, children: [], else_children: [] };
    const noElse = { type: "if", when: { module: "decisions" }, children: [text("Only")] };
    const t = tree(withElse, emptyElse, noElse, { type: "each", source: { record_type: "requirement" }, as: "r", children: [{ type: "page_break" }] });
    await expect(stableJson(roundTrip(t))).toBe(stableJson(t));
    const back = roundTrip(t).nodes as Record<string, unknown>[];
    await expect(back[2]).not.toHaveProperty("else_children");
    await expect(back[1].else_children).toEqual([]);
  },
};

export const AModulesBlockWithItsOwnChildListNeedsNoCodeHere: Story = {
  play: async () => {
    const t = tree({ type: "panel", title: "P", body: [text("Inside"), { type: "panel", body: [] }] });
    await expect(stableJson(roundTrip(t, withModuleBlock))).toBe(stableJson(t));
    const doc = treeToDoc(t, withModuleBlock);
    await expect(doc.content![0].type).toBe(DOC.block);
    await expect(doc.content![0].content![0]).toMatchObject({ type: DOC.slot, attrs: { key: "body" } });
  },
};

export const ABlockTheCatalogueDoesNotKnowIsCarriedWhole: Story = {
  play: async () => {
    const t = tree({ type: "mystery", size: 3, nested: { a: [1, 2] } }, { type: "widget", key: "a.b.c", params: { n: { var: "v" } }, sort: [{ column: "X" }] });
    await expect(stableJson(roundTrip(t))).toBe(stableJson(t));
    await expect(treeToDoc(t, types).content!.map((n) => n.type)).toEqual([DOC.leaf, DOC.leaf]);
  },
};

export const TheOtherKeysOfTheTreeAreKept: Story = {
  play: async () => {
    const t = { ...tree(text("x")), variables: [{ name: "v", type: "text" }] };
    const doc = treeToDoc(t, types);
    const back = docToTree({ ...doc, content: [] }, t);
    await expect(back.variables).toEqual(t.variables);
    await expect(back.orientation).toBe("portrait");
    await expect(back.nodes).toEqual([]);
  },
};

export const EditingTheDocumentWritesTheMarkdownBack: Story = {
  play: async () => {
    const t = tree(text("Old text"));
    const doc = treeToDoc(t, types);
    const paragraph = doc.content![0].content![0];
    // The author types a second paragraph and leaves an empty one and an empty bullet behind; the empties vanish.
    const edited: DocNode = {
      ...doc,
      content: [{
        ...doc.content![0],
        content: [
          { ...paragraph, content: [{ type: "text", text: "New text" }] },
          { type: DOC.paragraph },
          { type: DOC.bulletList, content: [{ type: DOC.listItem, content: [{ type: DOC.paragraph }] }] },
          { type: DOC.paragraph, content: [{ type: "text", text: "Third" }] },
        ],
      }],
    };
    await expect(docToTree(edited, t).nodes).toEqual([text("New text\n\nThird")]);
  },
};

export const ATreeThatCannotBeShownLosslesslyIsRefusedWithTheReason: Story = {
  play: async () => {
    const refused = async (t: Tree, path: string) => {
      let caught: unknown = null;
      try {
        treeToDoc(t, types);
      } catch (err) {
        caught = err;
      }
      await expect(caught).toBeInstanceOf(NotRepresentableError);
      await expect((caught as NotRepresentableError).path).toBe(path);
    };
    await refused(tree({ type: "heading" }), "nodes[0]");
    await refused(tree({ type: "text", text: 3 }), "nodes[0]");
    await refused(tree({ type: "each", children: "nope" }), "nodes[0].children");
    await refused({ schema_version: 1, family: "document" }, "nodes");
  },
};

export const StylesAreMarksOnTheEditorsTextAndListsAreNodes: Story = {
  play: async () => {
    const doc = treeToDoc(tree(text("A **bold** and *it* and `co` and ***bi***.\n\n1. one\n2. **two**")), types);
    const [paragraph, list] = doc.content![0].content!;
    await expect(paragraph.content!.map((n) => [n.text, n.marks?.map((m) => m.type) ?? []])).toEqual([
      ["A ", []], ["bold", ["bold"]], [" and ", []], ["it", ["italic"]], [" and ", []], ["co", ["code"]], [" and ", []], ["bi", ["bold", "italic"]], [".", []],
    ]);
    await expect(list.type).toBe(DOC.orderedList);
    await expect(list.content![1].content![0].content![0].marks).toEqual([{ type: "bold" }]);
  },
};

export const MarksOutsideTheWordsMoveBackOutOfTheMarkers: Story = {
  play: async () => {
    // A bold run that includes its surrounding spaces is written with the spaces outside, which is the only form the
    // server reads as bold.
    const nodes: DocNode[] = [
      { type: "text", text: "a" }, { type: "text", text: "  bold  ", marks: [{ type: "bold" }] }, { type: "text", text: "b" },
    ];
    await expect(serializeMarkdown([{ type: DOC.paragraph, content: nodes }])).toBe("a  **bold**  b");
  },
};

export const LiteralMarkersTheAuthorTypesAreEscapedSoTheyStayLiteral: Story = {
  play: async () => {
    const typed: DocNode[] = [{ type: "text", text: "a * b *c* `d` back\\ x_y _z" }];
    const markdown = serializeMarkdown([{ type: DOC.paragraph, content: typed }]);
    await expect(markdown).toBe("a * b \\*c\\* \\`d\\` back\\\\ x_y \\_z");
    // ...and reading that back gives the same words.
    await expect(textOfParagraph(parseMarkdown(markdown))).toBe("a * b *c* `d` back\\ x_y _z");
  },
};

export const CodeWithABacktickInItIsLeftAsSource: Story = {
  play: async () => {
    const t = tree(text("A ``a`b`` span"));
    await expect(treeToDoc(t, types).content![0].type).toBe(DOC.raw);
    await expect(stableJson(roundTrip(t))).toBe(stableJson(t));
  },
};

function textOfParagraph(nodes: DocNode[] | null): string {
  return (nodes?.[0].content ?? []).map((n) => n.text ?? "").join("");
}

export const LinksAreMarksCarryingTheirAddress: Story = {
  play: async () => {
    const doc = treeToDoc(tree(text("Go [to **it**](https://example.org/x) now")), types);
    const nodes = doc.content![0].content![0].content!;
    await expect(nodes.map((n) => [n.text, n.marks?.map((m) => [m.type, m.attrs?.href ?? null]) ?? []])).toEqual([
      ["Go ", []],
      ["to ", [["link", "https://example.org/x"]]],
      ["it", [["bold", null], ["link", "https://example.org/x"]]],
      [" now", []],
    ]);
  },
};

export const ALinkIsWrittenWithItsEdgeSpacesOutsideTheBrackets: Story = {
  play: async () => {
    const link = (text: string) => ({ type: "text", text, marks: [{ type: "link", attrs: { href: "https://e.org" } }] });
    const nodes: DocNode[] = [{ type: "text", text: "a" }, link("  words "), { type: "text", text: "b" }];
    await expect(serializeMarkdown([{ type: DOC.paragraph, content: nodes }])).toBe("a  [words](https://e.org) b");
    // Two neighbouring runs of one link are one link.
    const two: DocNode[] = [link("one "), { ...link("two"), marks: [{ type: "bold" }, { type: "link", attrs: { href: "https://e.org" } }] }];
    await expect(serializeMarkdown([{ type: DOC.paragraph, content: two }])).toBe("[one **two**](https://e.org)");
  },
};

export const BracketsInLinkTextAreEscapedAndOrdinaryBracketsAreNot: Story = {
  play: async () => {
    const link = (text: string): DocNode => ({ type: "text", text, marks: [{ type: "link", attrs: { href: "https://e.org" } }] });
    await expect(serializeMarkdown([{ type: DOC.paragraph, content: [link("see [1]")] }])).toBe("[see \\[1\\]](https://e.org)");
    await expect(serializeMarkdown([{ type: DOC.paragraph, content: [{ type: "text", text: "see [1]" }] }])).toBe("see [1]");
  },
};

export const AddressesAndAnchorsFollowTheServersRulesOnEveryVector: Story = {
  play: async () => {
    for (const href of linkVectors.links.allowed) await expect(linkProblem(href), href).toBeNull();
    for (const href of linkVectors.links.refused) await expect(linkProblem(href), JSON.stringify(href)).not.toBeNull();
    for (const [words, anchor] of linkVectors.anchors) await expect(headingAnchor(words), words).toBe(anchor);
  },
};

export const AProblemMessageNeverRepeatsTheAddress: Story = {
  play: async () => {
    for (const href of linkVectors.links.refused.filter((h) => h.length > 3)) await expect(linkProblem(href)).not.toContain(href);
  },
};

export const SectionsAreTheHeadingsWithTheAnchorsTheReportWillGiveThem: Story = {
  play: async () => {
    const t = tree(
      { type: "heading", text: "Overview" },
      text("# Scope & Goals\n\nBody text\n\n## Overview"),
      { type: "each", source: { record_type: "requirement" }, children: [{ type: "heading", text: "{{record.title}}" }, { type: "heading", text: "Detail" }] },
      { type: "if", when: { module: "decisions" }, children: [{ type: "heading", text: "Overview" }], else_children: [text("# Detail")] },
    );
    await expect(sectionsOf(t)).toEqual([
      { label: "Overview", anchor: "overview" },
      { label: "Scope & Goals", anchor: "scope-goals" },
      { label: "Overview", anchor: "overview-2" },
      { label: "Detail", anchor: "detail" },
      { label: "Overview", anchor: "overview-3" },
      { label: "Detail", anchor: "detail-2" },
    ]);
  },
};
