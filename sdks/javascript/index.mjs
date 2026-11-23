/**
 * Dependency-free JavaScript client for Memo Cup.
 * Requires a running local Memo Cup API (`memocup serve`).
 */
export class MemoCupClient {
  constructor({ baseUrl = "http://127.0.0.1:8765", apiKey, timeoutMs = 10000 } = {}) {
    if (!apiKey || typeof apiKey !== "string") {
      throw new TypeError("apiKey is required.");
    }
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.apiKey = apiKey;
    this.timeoutMs = timeoutMs;
  }

  async request(path, { method = "GET", body } = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        method,
        signal: controller.signal,
        headers: {
          Authorization: `Bearer ${this.apiKey}`,
          Accept: "application/json",
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      const text = await response.text();
      let payload;
      try {
        payload = text ? JSON.parse(text) : null;
      } catch {
        throw new Error(`Memo Cup returned invalid JSON (HTTP ${response.status}).`);
      }
      if (!response.ok) {
        throw new Error(`Memo Cup API returned HTTP ${response.status}: ${payload?.message ?? payload?.error ?? "Unknown error"}`);
      }
      return payload;
    } catch (error) {
      if (error?.name === "AbortError") {
        throw new Error(`Memo Cup request timed out after ${this.timeoutMs} ms.`);
      }
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  health() {
    return this.request("/health");
  }

  async remember(content, options = {}) {
    if (typeof content !== "string" || !content.trim()) {
      throw new TypeError("Memory content must be a non-empty string.");
    }
    const result = await this.request("/v1/memories", {
      method: "POST",
      body: { content, ...options },
    });
    return result.memory;
  }

  async recall(query, options = {}) {
    const result = await this.request("/v1/recall", {
      method: "POST",
      body: {
        query,
        limit: options.limit ?? 8,
        categories: options.categories ?? [],
        scopes: options.scopes ?? ["project", "user"],
      },
    });
    return result.memories;
  }

  async context(query, options = {}) {
    const result = await this.request("/v1/context", {
      method: "POST",
      body: {
        query,
        limit: options.limit ?? 8,
        max_chars: options.maxChars ?? 12000,
        categories: options.categories ?? [],
        scopes: options.scopes ?? ["project", "user"],
      },
    });
    return result.context;
  }

  async prepareMessages(messages, options = {}) {
    if (!Array.isArray(messages)) throw new TypeError("messages must be an array.");
    const query = options.query ?? lastUserText(messages);
    const memoryContext = await this.context(query, options);
    const cloned = messages.map((message) => ({ ...message }));
    const systemRole = options.systemRole ?? "system";
    const systemIndex = cloned.findIndex((message) => message.role === systemRole && typeof message.content === "string");
    if (systemIndex >= 0) {
      cloned[systemIndex] = {
        ...cloned[systemIndex],
        content: `${cloned[systemIndex].content}\n\n${memoryContext}`,
      };
      return cloned;
    }
    return [{ role: systemRole, content: memoryContext }, ...cloned];
  }

  async forget(memoryId) {
    const result = await this.request(`/v1/memories/${encodeURIComponent(memoryId)}`, { method: "DELETE" });
    return Boolean(result?.forgotten);
  }
}

function lastUserText(messages) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message?.role !== "user") continue;
    if (typeof message.content === "string") return message.content;
    if (Array.isArray(message.content)) {
      return message.content
        .filter((part) => part && typeof part === "object" && typeof part.text === "string")
        .map((part) => part.text)
        .join(" ");
    }
  }
  return "";
}
