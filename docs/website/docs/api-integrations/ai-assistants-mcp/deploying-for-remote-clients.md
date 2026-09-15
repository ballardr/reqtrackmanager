---
sidebar_position: 6
---

# Deploying for remote clients (Copilot Studio, etc.)

A cloud service like Microsoft Copilot Studio needs a publicly-reachable URL, not `localhost`. The same reverse-proxy pattern used for the REST API itself (see [Installation & Deployment → TLS, reverse proxy, and same-origin deployment](../../installation-deployment/tls-and-reverse-proxy.md)) applies here — add one more `location` block:

```nginx
location /mcp/ {
    proxy_pass http://mcp-server:8100;
    proxy_set_header Host $host;
    # Streamable HTTP keeps a connection open for server-initiated
    # messages — make sure buffering/timeouts don't cut that off:
    proxy_buffering off;
    proxy_read_timeout 3600s;
}
```

Then the MCP URL you give any remote client is `https://my.website.com/mcp/mcp` (the proxy's own `/mcp/` prefix, plus the server's own `/mcp` endpoint path underneath it) — or adjust the `location` match/`proxy_pass` target if you'd rather it resolve to a cleaner external path.

**Always put this behind TLS in production**, same as the rest of the stack — the bearer token travels in a plain HTTP header, exactly like every other authenticated request this app makes, and is only as safe as the transport it rides over.

## Where this fits

See [Setting up Microsoft Copilot Studio](./setting-up-microsoft-copilot-studio.md) for the client-side configuration once this is exposed, and [Installation & Deployment → TLS, reverse proxy, and same-origin deployment](../../installation-deployment/tls-and-reverse-proxy.md) for the rest of the reverse-proxy setup this reuses.
