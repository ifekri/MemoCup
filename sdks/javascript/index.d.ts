export type MemoryCategory =
  | "fact"
  | "preference"
  | "decision"
  | "constraint"
  | "task"
  | "entity"
  | "procedure"
  | "correction"
  | "conversation"
  | "note";

export type MemoryScope = "project" | "user";

export interface MemoCupClientOptions {
  baseUrl?: string;
  apiKey: string;
  timeoutMs?: number;
}

export interface RememberOptions {
  category?: MemoryCategory;
  scope?: MemoryScope;
  tags?: string[];
  source?: string;
  source_ref?: string;
  confidence?: number;
  importance?: number;
  metadata?: Record<string, unknown>;
  supersedes_id?: string;
  expires_at?: string;
}

export interface RecallOptions {
  limit?: number;
  categories?: MemoryCategory[];
  scopes?: MemoryScope[];
}

export interface ContextOptions extends RecallOptions {
  maxChars?: number;
  systemRole?: string;
}

export interface MemoryRecord {
  id: string;
  project_id: string;
  scope: MemoryScope;
  category: MemoryCategory;
  content: string;
  tags: string[];
  source: string;
  source_ref: string | null;
  confidence: number;
  importance: number;
  status: "active" | "superseded" | "archived" | "forgotten";
  metadata: Record<string, unknown>;
  supersedes_id: string | null;
  superseded_by: string | null;
  created_at: string;
  updated_at: string;
  last_accessed_at: string | null;
  expires_at: string | null;
  score?: number;
}

export declare class MemoCupClient {
  constructor(options: MemoCupClientOptions);
  health(): Promise<{ ok: boolean; service: string; version: string }>;
  remember(content: string, options?: RememberOptions): Promise<MemoryRecord>;
  recall(query: string, options?: RecallOptions): Promise<MemoryRecord[]>;
  context(query: string, options?: ContextOptions): Promise<string>;
  prepareMessages<T extends Record<string, unknown>>(messages: T[], options?: ContextOptions & { query?: string }): Promise<T[]>;
  forget(memoryId: string): Promise<boolean>;
}
