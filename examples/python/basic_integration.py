"""Minimal provider-agnostic Memo Cup integration example."""

import os
from memocup import MemoCupClient

memory = MemoCupClient(
    os.getenv("MEMOCUP_URL", "http://127.0.0.1:8765"),
    api_key=os.environ["MEMOCUP_API_KEY"],
)

messages = [
    {"role": "system", "content": "You are a careful coding assistant."},
    {"role": "user", "content": "Which deployment target did we choose for this project?"},
]

# Add relevant memory to the prompt before sending it to your chosen model provider.
messages_with_memory = memory.prepare_messages(messages)

# Pass messages_with_memory to your model provider here.
# After the user explicitly confirms a durable decision, persist it:
memory.remember(
    "The project deployment target is the user's chosen hosting platform.",
    category="decision",
    source="user",
    confidence=1.0,
    importance=5,
    tags=["deployment", "hosting"],
)
