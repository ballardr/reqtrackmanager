/**
 * Module: architecture/help
 *
 * The `(?)` field help for this module's own fields (docs/ux-style-guide.md, "Pattern: field help").
 * It lives in the module, not in the core string table, so a module's copy never needs a core edit.
 * One or two sentences per field: what it is, what it affects, a typical value.
 */

/** Help text for the System Architecture module's form fields, passed as `help` to the shared field components. */
export const ARCHITECTURE_HELP = {
  elementType: "What kind of part this is (a service, a board, a datastore). It sets how the element is drawn and which parts it is grouped with.",
  elementParent: "The element this one is a part of. Parents form a tree up to 12 levels deep; a diagram can open a parent to show its children.",
  elementOwner: "The person or group accountable for this part of the product.",
  elementSymbol: "A drawing shown instead of the type's. Leave it empty to use the type's own symbol or shape.",
  elementActivate: "Creates the element as Active instead of Draft. An element has no approval step, so this needs no more than permission to create.",
  elementPorts: "Named attachment points where connections meet the element, one per interface (for example an API or a bus). Each can carry a connection type.",
  portDirection: "Which way traffic crosses the port, seen from this element: In, Out or Both.",
  portConnectionType: "The kind of connection this port expects. Optional; a connection may still use the port with another type.",
  typeDomain: "Whether the type suits software, hardware or both. It narrows the choices offered when a diagram view is filtered by domain.",
  typeShape: "The outline used to draw elements of this type when no symbol is set.",
  typeColor: "The fill colour used for elements of this type, for light and dark themes. Leave empty for the default colour.",
  typeSymbol: "A drawing from the symbol library shown for every element of this type. A single element can override it.",
  connectionLineStyle: "How lines of this type are drawn in a diagram: solid, dashed or dotted.",
  connectionDirectional: "A one-way type runs from the source to the target; a two-way type shows no arrow and the order of its ends is for display only.",
  connectionType: "The kind of interface (REST API, message queue, I2C bus). It sets how the line is drawn when a diagram shows connection detail.",
  connectionSource: "The element the connection starts from. It may be one of this project's elements or one that another owner shares with the project.",
  connectionTarget: "The element the connection ends at. It must differ from the source.",
  connectionPort: "The port on this end the connection uses. Optional.",
  connectionProtocol: "The protocol or version carried, for example HTTPS/1.1 or SPI mode 0. Free text.",
  collectionMembers: "The elements shared by this collection. Their child elements are shared with them.",
  collectionGrant: "Who may read the collection's elements, place them in diagrams, connect to them and link to them. A recipient never edits them.",
  collectionIncludeDescendants: "Also reaches every project nested under the chosen project, including projects added later.",
  diagramScope: "The element whose inside the diagram shows: its child elements are the ones offered and placed. Leave it empty for the system context, which shows the top-level elements.",
  diagramConnectionDetail: "Off draws plain lines; several connections between the same two boxes collapse into one. On draws each connection with its type, protocol and colour.",
  diagramPopulate: "Places the scope element's child elements (or the top-level elements for the system context) on the diagram in a grid. You can move, add and remove boxes afterwards.",
  diagramActivate: "Creates the diagram as Active instead of Draft. A diagram has no approval step, so this needs no more than permission to create.",
  toggleName: "The name shown on the switch (for example Security devices). It is also what a report or export lists when it names the switch.",
  toggleDefault: "Whether the switch starts on. A report or export uses this state unless it names another. Viewers can flip the switch on the page without saving.",
  toggleRule: "Elements and connections that belong to the switch by type, domain or tag, besides any chosen by hand. Switching it off hides all of them; a hidden element between two others is bridged by a dashed line.",
  toggleMembers: "Elements and connections chosen by hand. They belong to the switch together with those its rule matches.",
  connectionPrompt: "Connections are real records: this one is created in the model and drawn here, and it appears on both elements and in the Connections list.",
  symbolUpload: "An SVG drawing (or an EPS or PDF when conversion is available). It is sanitised on upload. Upload only artwork the organisation is licensed to use.",
} as const;
