import { MemoCupClient } from "../../sdks/javascript/index.mjs";

const memory = new MemoCupClient({
  baseUrl: process.env.MEMOCUP_URL ?? "http://127.0.0.1:8765",
  apiKey: process.env.MEMOCUP_API_KEY,
});

const messages = [
  { role: "system", content: "You are a careful assistant. Verify claims and disclose uncertainty." },
  { role: "user", content: "What architecture decision did we make earlier?" },
];

// Send the enriched messages to your chosen model provider.
const messagesWithMemory = await memory.prepareMessages(messages);
console.log(messagesWithMemory);

// Persist explicit, durable decisions after they are confirmed.
await memory.remember("The service uses a modular monolith architecture.", {
  category: "decision",
  scope: "project",
  source: "user",
  confidence: 1,
  importance: 5,
  tags: ["architecture"],
});
