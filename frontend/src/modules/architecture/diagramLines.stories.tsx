import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { buildConnection, buildDiagramModel, buildModelElement, MODEL_REST_TYPE } from "./architectureFixtures";
import { edgeLabelText, resolveDiagram } from "./diagramLines";

const state = (overrides: Partial<Parameters<typeof resolveDiagram>[1]> = {}) => ({
  placed: ["el-1", "el-2", "el-3"], togglesOff: new Set<string>(), connectionDetail: true, ...overrides,
});

function Host() {
  return <p>Shapes the lines the browser resolves like the server's resolved view.</p>;
}

const meta: Meta<typeof Host> = { title: "Modules/Architecture/DiagramLines", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

export const ALineCarriesItsTypeAndProtocolWhenDetailIsOn: Story = {
  play: async () => {
    const { edges } = resolveDiagram(buildDiagramModel(), state());
    expect(edges).toHaveLength(1);
    expect(edges[0]).toMatchObject({
      id: "el-1-el-2-con-1", source_element_id: "el-1", target_element_id: "el-2", count: 1, type_name: "REST API",
      line_style: "solid", label: "REST API · HTTPS/1.1", indirect: false, bridged: false, rolled_up: false, two_way: false,
    });
    expect(edges[0].connections.map((c) => c.id)).toEqual(["con-1"]);
  },
};

export const APlainDiagramHasNoTypeOrLabelAndMergesParallelLines: Story = {
  play: async () => {
    const model = buildDiagramModel({ connections: [buildConnection(), buildConnection({ id: "con-2", unique_code: "CON-002" })] });
    const [edge] = resolveDiagram(model, state({ connectionDetail: false })).edges;
    expect(edge).toMatchObject({ count: 2, type_name: null, line_style: null, label: null });
    // With detail on, direct parallel connections keep their own lines.
    expect(resolveDiagram(model, state()).edges.map((e) => e.label)).toEqual(["REST API · HTTPS/1.1", "REST API · HTTPS/1.1"]);
  },
};

/** Two parts inside Orders, each connected from Gateway, so the connections roll up to one line. */
const ROLLED_UP = {
  elements: [
    ...buildDiagramModel().elements,
    buildModelElement({ id: "el-5", unique_code: "ELM-005", name: "Orders API" }),
    buildModelElement({ id: "el-6", unique_code: "ELM-006", name: "Orders DB" }),
  ],
  parents: { "el-1": null, "el-2": null, "el-3": null, "el-4": null, "el-5": "el-2", "el-6": "el-2" },
};

export const RolledUpConnectionsOfOneTypeShareALabelWithTheirCount: Story = {
  play: async () => {
    const model = buildDiagramModel({
      ...ROLLED_UP,
      connections: [buildConnection({ id: "con-a", target_element_id: "el-5" }), buildConnection({ id: "con-b", target_element_id: "el-6" })],
    });
    const [edge] = resolveDiagram(model, state()).edges;
    expect(edge).toMatchObject({ target_element_id: "el-2", rolled_up: true, indirect: true, count: 2, type_name: "REST API", label: "REST API ×2" });
  },
};

export const ConnectionsOfDifferentTypesShareNoType: Story = {
  play: async () => {
    const model = buildDiagramModel({
      ...ROLLED_UP,
      connections: [
        buildConnection({ id: "con-a", target_element_id: "el-5" }),
        buildConnection({ id: "con-b", target_element_id: "el-6", connection_type_id: "ct-2" }),
      ],
      connection_types: [MODEL_REST_TYPE, { ...MODEL_REST_TYPE, id: "ct-2", name: "I2C" }],
    });
    const [edge] = resolveDiagram(model, state()).edges;
    expect(edge).toMatchObject({ count: 2, type_name: null, label: "2 connections" });
  },
};

export const AHiddenElementIsBridgedAndNamedOnlyWhenReadable: Story = {
  play: async () => {
    const connections = [
      buildConnection({ id: "con-in", source_element_id: "el-1", target_element_id: "el-3" }),
      buildConnection({ id: "con-out", source_element_id: "el-3", target_element_id: "el-2" }),
    ];
    const open = resolveDiagram(buildDiagramModel({ connections }), state({ togglesOff: new Set(["tg-1"]) }));
    expect([...open.hidden]).toEqual(["el-3"]);
    expect(open.edges).toHaveLength(1);
    expect(open.edges[0]).toMatchObject({ source_element_id: "el-1", target_element_id: "el-2", bridged: true, indirect: true });
    expect(open.edges[0].hops).toEqual([{ element_id: "el-3", unique_code: "ELM-003", name: "Firewall" }]);

    const locked = buildDiagramModel({
      connections,
      elements: buildDiagramModel().elements.map((e) => (e.id === "el-3" ? buildModelElement({ ...e, name: "", locked: true }) : e)),
    });
    expect(resolveDiagram(locked, state({ togglesOff: new Set(["tg-1"]) })).edges[0].hops).toEqual([]);
  },
};

export const ABoxNotYetSavedStillGetsItsLines: Story = {
  play: async () => {
    const model = buildDiagramModel({ connections: [buildConnection({ id: "con-5", target_element_id: "el-4" })] });
    expect(resolveDiagram(model, state()).edges).toHaveLength(0);
    const added = resolveDiagram(model, state({ placed: ["el-1", "el-2", "el-3", "el-4"] }));
    expect(added.edges.map((e) => [e.source_element_id, e.target_element_id])).toEqual([["el-1", "el-4"]]);
  },
};

export const AConnectionToAnUnknownElementIsLeftOut: Story = {
  play: async () => {
    const model = buildDiagramModel({ connections: [buildConnection({ target_element_id: "el-missing" })] });
    expect(resolveDiagram(model, state()).edges).toEqual([]);
  },
};

export const TheLabelOfASingleConnectionNamesItsTypeAndProtocol: Story = {
  play: async () => {
    expect(edgeLabelText(1, "REST API", "HTTPS")).toBe("REST API · HTTPS");
    expect(edgeLabelText(1, "REST API", "")).toBe("REST API");
    expect(edgeLabelText(1, undefined, "HTTPS")).toBe("HTTPS");
    expect(edgeLabelText(1, undefined, "")).toBeNull();
    expect(edgeLabelText(3, "REST API", "HTTPS")).toBe("REST API ×3");
    expect(edgeLabelText(3, undefined, "")).toBe("3 connections");
  },
};
