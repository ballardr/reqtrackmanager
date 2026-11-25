import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn } from "storybook/test";

import {
  AUTH_UNAUTHORIZED_EVENT,
  INVALID_TOKEN_CODE,
  NETWORK_FAILURE_MESSAGE,
  REQUEST_TIMEOUT_MESSAGE,
  api,
  isDeadSessionResponse,
  setAuthToken,
} from "./client";

/**
 * How the client decides a refused request ends the session, and the ceiling an ordinary read is given. The page is
 * a placeholder: every check is in the interactions, against a replaced `fetch`.
 */
const meta: Meta = { title: "Utils/apiClient", render: () => <p>Request handling; see the interactions.</p> };
export default meta;

type Story = StoryObj;

/** A response as the browser hands it to the client: its header may be hidden from a page on another origin. */
function refusal(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

const DEAD_BODY = { detail: "Could not validate credentials.", code: INVALID_TOKEN_CODE };

/** Runs `work` with the client signed in as `token`, counting the sessions it reports dead, then restores everything. */
async function withSession(token: string, answer: (init: RequestInit, url: string) => Promise<Response>, work: (ended: () => number) => Promise<void>) {
  let ended = 0;
  const count = () => {
    ended += 1;
  };
  window.addEventListener(AUTH_UNAUTHORIZED_EVENT, count);
  const fetchSpy = spyOn(window, "fetch").mockImplementation((url, init) => answer(init ?? {}, String(url)));
  setAuthToken(token);
  try {
    await work(() => ended);
  } finally {
    setAuthToken(null);
    fetchSpy.mockRestore();
    window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, count);
  }
}

async function refused(call: Promise<unknown>): Promise<void> {
  await call.then(
    () => {
      throw new Error("The request was expected to be refused.");
    },
    () => undefined,
  );
}

export const EitherSignalAloneEndsTheSession: Story = {
  play: async () => {
    await expect(isDeadSessionResponse(401, "Bearer", null)).toBe(true);
    await expect(isDeadSessionResponse(401, null, DEAD_BODY)).toBe(true);
    await expect(isDeadSessionResponse(401, null, { detail: "Current password is incorrect." })).toBe(false);
    await expect(isDeadSessionResponse(401, null, null)).toBe(false);
    await expect(isDeadSessionResponse(403, "Bearer", DEAD_BODY)).toBe(false);
  },
};

/** The fault this guards: a cross-origin browser reads no `WWW-Authenticate`, so the body marker has to do the work. */
export const AMarkerInTheBodyEndsTheSessionWhenTheHeaderIsHidden: Story = {
  play: async () => {
    await withSession("token-a", async () => refusal(401, DEAD_BODY), async (ended) => {
      await refused(api.get("/api/v1/projects"));
      await expect(ended()).toBe(1);
    });
  },
};

export const AHeaderAloneEndsTheSessionWhenTheBodyHasNoMarker: Story = {
  play: async () => {
    await withSession("token-a", async () => refusal(401, { detail: "Could not validate credentials." }, { "WWW-Authenticate": "Bearer" }), async (ended) => {
      await refused(api.get("/api/v1/projects"));
      await expect(ended()).toBe(1);
    });
  },
};

export const AWrongPasswordDoesNotEndTheSession: Story = {
  play: async () => {
    await withSession("token-a", async () => refusal(401, { detail: "Current password is incorrect." }), async (ended) => {
      await refused(api.post("/api/v1/auth/change-password", { current_password: "x", new_password: "y" }));
      await expect(ended()).toBe(0);
    });
  },
};

/** Several requests refused together end the session once: the first clears the token, so the rest find it no longer current. */
export const SeveralRefusalsEndTheSessionOnce: Story = {
  play: async () => {
    await withSession("token-a", async () => refusal(401, DEAD_BODY), async (ended) => {
      await Promise.all([1, 2, 3, 4].map((n) => refused(api.get(`/api/v1/projects?n=${n}`))));
      await expect(ended()).toBe(1);
    });
  },
};

/** A late refusal for a request the previous session sent must not sign out the session that replaced it. */
export const ALateRefusalFromAnEarlierSessionIsIgnored: Story = {
  play: async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    await withSession(
      "token-old",
      async () => {
        await gate;
        return refusal(401, DEAD_BODY);
      },
      async (ended) => {
        const late = refused(api.get("/api/v1/projects"));
        setAuthToken("token-new");
        release();
        await late;
        await expect(ended()).toBe(0);
      },
    );
  },
};

/** A request sent with no session (the sign-in call itself) has nothing to end. */
export const ARefusalWithoutASessionEndsNothing: Story = {
  play: async () => {
    await withSession("", async () => refusal(401, DEAD_BODY), async (ended) => {
      setAuthToken(null);
      await refused(api.post("/api/v1/auth/login", { email: "a", password: "b" }));
      await expect(ended()).toBe(0);
    });
  },
};

/** An ordinary read gets the default ceiling; a write, an upload and a download wait as long as they need. */
export const OnlyAnOrdinaryReadGetsTheDefaultCeiling: Story = {
  play: async () => {
    const hasCeiling: Record<string, boolean> = {};
    await withSession(
      "token-a",
      async (init, url) => {
        hasCeiling[url.replace(/^.*\/api\/v1\//, "")] = init.signal !== undefined && init.signal !== null;
        return refusal(200, {});
      },
      async () => {
        await api.get("/api/v1/read");
        await api.getPage("/api/v1/page");
        await api.postPage("/api/v1/page-post", {});
        await api.post("/api/v1/write", {});
        await api.put("/api/v1/put", {});
        await api.getForBlob("/api/v1/download");
      },
    );
    await expect(hasCeiling).toEqual({ read: true, page: true, "page-post": true, write: false, put: false, download: false });
  },
};

/** A request that does not answer within its ceiling ends with a message the page can show, not a spinner that never ends. */
export const ARequestThatOutlivesItsCeilingFailsWithAMessage: Story = {
  play: async () => {
    await withSession(
      "token-a",
      (init) => new Promise<Response>((_resolve, reject) => init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")))),
      async () => {
        const error = await api.post("/api/v1/slow", {}, 30).then(
          () => null,
          (err: unknown) => err as Error & { status?: number },
        );
        await expect(error?.message).toBe(REQUEST_TIMEOUT_MESSAGE);
        await expect(error?.status).toBe(0);
      },
    );
  },
};

export const AnUnreachableServerFailsWithAMessage: Story = {
  play: async () => {
    await withSession(
      "token-a",
      async () => {
        throw new TypeError("Failed to fetch");
      },
      async () => {
        const error = await api.get("/api/v1/projects").then(
          () => null,
          (err: unknown) => err as Error & { status?: number },
        );
        await expect(error?.message).toBe(NETWORK_FAILURE_MESSAGE);
        await expect(error?.status).toBe(0);
      },
    );
  },
};
