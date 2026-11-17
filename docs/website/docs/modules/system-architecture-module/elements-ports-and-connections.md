---
sidebar_position: 1
---

# Elements, ports and connections

The architecture of a product is recorded as **elements** (its parts) and **connections** (how the parts talk to each other). Each is a coded record that can be linked, tagged, commented on and searched, and each is listed on its own tab of **System Architecture**.

## Terms used here

| Term | Meaning |
| --- | --- |
| [Element](../../reference/glossary.md#element) | A part of the product, such as a service or a board (`ELM-001`) |
| [Port](../../reference/glossary.md#port) | A named point where a connection meets an element |
| [Connection](../../reference/glossary.md#connection) | A link between two elements (`CON-001`) |
| [Connection type](../../reference/glossary.md#connection-type) | The kind of interface, such as REST API or I2C bus |
| [Domain](../../reference/glossary.md#domain) | A name an element type or connection type can be in, such as Software or Hardware |
| [Display note](../../reference/glossary.md#display-note) | A short line drawn inside an element's box on every diagram |
| [Symbol](../../reference/glossary.md#symbol) | A drawing from the symbol library, shown in an element's box |

```mermaid
flowchart LR
    subgraph G["Gateway (element)"]
        GP["Port: HTTPS API"]
    end
    subgraph S["Orders service (element)"]
        SP["Port: REST in"]
    end
    GP -- "Connection: REST API" --> SP
```

## Elements

An element has a name, a description, a type (which sets how it is drawn), an optional parent, an owner and a status. Parents form a tree up to 12 levels deep: a diagram can show a parent as one box, or open it to show its children. An element belongs to a project or to the organisation; an organisation element can be shared with projects through collections.

The **symbol** field chooses the drawing shown in the element's box; left empty, the element uses its type's symbol. The field is one button showing the current drawing and name; it opens a panel with a **Search** field above, the symbols in the middle and view buttons below. **List** shows the symbol names, **Gallery** a scrolling grid that shows every drawing, and **Upload** (offered only to a person who may change the library) adds a new drawing and chooses it. Both choices include **None**, which returns to the default. The List or Gallery choice is remembered in the browser. The arrow keys move between rows or tiles, Enter or Space chooses, and Escape closes the panel.

A person with the Architecture Admin role (Architecture Org Admin for an organisation's elements and types) also sees **Upload a symbol** under the field. The file is sanitised, added to the shared symbol library of the project (or organisation) for everyone, and chosen in the form; the choice is saved with the form. Rename or remove the symbol later under **Symbols** in the settings. Everyone else sees the field without the upload, and the server refuses an upload from them.

The **display note** is one line, up to 500 characters, drawn inside the element's box. It is separate from the description, which is for the record, reports and search.

## Ports

A **port** is a named point where a connection meets an element, one for each interface, for example "CAN bus" or "Power in". Ports are optional: an element with none still takes connections, and a port only lets a connection say which interface it uses.

| Direction | Meaning |
| --- | --- |
| In | Traffic arrives at the element |
| Out | Traffic leaves the element |
| Both | Traffic crosses either way, as on a bus |

A port may also name the connection type it expects. This is guidance: a connection may still use the port with another type.

## Connections

A connection joins a source element to a target element, which must differ. Each end may name one of its element's ports. A connection has a type, an optional protocol (for example HTTPS/1.1 or SPI mode 0) and a description. A connection of a one-way type runs from source to target; a two-way type shows no arrow and the order of its ends is for display only.

Connection types are organised in groups: a type such as I2C can sit under Serial bus and under Board-to-board, and choosing a group also reaches every type beneath it when connections are filtered. When a connection is created, the type list offers the types that suit both elements first: a type suits an element when the two share a [domain](../../reference/glossary.md#domain), or when either is in no domain.

## Domains

A **domain** is a name that element types and connection types can be in, such as Software, Hardware or Mechanical. A new organisation has Software and Hardware; add the domains your teams work in under **Domains** in the System Architecture settings, for the organisation or for one project. A type can be in several domains, or in none, which means it fits every domain.

Domains narrow the choices; they never forbid one:

- The connection type list offers the types that share a domain with both elements, and a type that does not fit can still be chosen, with a warning that names the domains.
- **Add to diagram** lists an element type under each domain it is in (for example **New hardware element**), and a type in no domain under **New element**.
- The **Domain** filter of **Add existing elements** shows the elements whose type is in the domain, or in none.
- A view switch can match by domain: it matches the elements and connections whose type is in any chosen domain.

The two tiers work as for the types: an organisation's domains are offered in every project, a project can add its own and hide an organisation default it does not use (**Add organisation defaults** brings it back), and a child project without domains of its own shows the nearest parent's. A domain that a type is in, or that a view switch names, cannot be deleted. Hiding a domain stops new use only: a type already in it keeps it.

Either end may be an element the project can read from elsewhere: another project's element shared with it, or an organisation element. The connection belongs to the project that created it.
