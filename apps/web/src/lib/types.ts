// Shapes returned by the FastAPI backend (apps/api/routes/*.py, apps/api/profiler/*.py).

export type Project = {
  id: number;
  title: string;
  topic: string | null;
  status: string;
  share_samples: boolean;
  created_at: string;
};

export type DatasetStatus =
  "queued" | "loading" | "profiling" | "ready" | "failed";

export type Dataset = {
  id: number;
  table_name: string;
  original_filename: string;
  status: DatasetStatus;
  error: string | null;
  row_count: number | null;
  column_count: number | null;
  size_bytes: number;
  describe_status: string | null;
  describe_error: string | null;
  kind: "upload" | "combined";
  source_json: {
    mode: "stack" | "join";
    labels?: string[];
    how?: "left" | "inner";
  } | null;
  created_at: string;
};

export type Severity = "info" | "warning" | "severe";

export type DataWarning = {
  code: string;
  severity: Severity;
  message: string;
  column: string | null;
  details: Record<string, unknown>;
};

export type TopValue = { value: string; count: number; share: number };

export type ColumnProfile = {
  kind: "numeric" | "datetime" | "text" | "boolean" | "other";
  physical_type: string;
  semantic_type: string;
  count: number;
  non_null: number;
  missing: number;
  missing_pct: number;
  distinct: number;
  uniqueness: number;
  top_values?: TopValue[];
  categorical?: {
    rare_categories: number;
    imbalance_ratio: number;
    top_share: number;
  };
  numeric?: {
    finite: number;
    min: number;
    max: number;
    mean: number;
    median: number;
    std: number | null;
    skew: number | null;
    quantiles: Record<"p05" | "p25" | "p50" | "p75" | "p95", number>;
    zeros: number;
    negatives: number;
    outliers: number;
    histogram: { start: number; end: number; count: number }[];
  };
  datetime?: {
    min: string;
    max: string;
    granularity: string;
    period: string;
    counts: { period: string; count: number }[];
    empty_periods: number;
  };
  text?: {
    min_length: number;
    avg_length: number;
    max_length: number;
    blank: number;
    avg_words: number;
    samples: string[];
  };
};

export type Column = {
  id: number;
  name: string;
  original_name: string | null;
  physical_type: string;
  semantic_type: string | null;
  description: string | null;
  description_source: "llm" | "user" | "dictionary" | null;
  description_confidence: "high" | "medium" | "low" | null;
  is_pii: boolean;
  pii_reason: string | null;
  profile_json: ColumnProfile | null;
};

export type TableProfile = {
  row_count: number;
  column_count: number;
  duplicate_rows: number;
  candidate_keys: string[];
  semantic_types: Record<string, number>;
  missing_cells: number;
  missing_cells_pct: number;
  relationships?: TableRelationships;
};

export type Association = {
  a: string;
  b: string;
  measure: "spearman" | "cramers_v" | "eta";
  value: number;
  n: number;
};

export type MissingDependency =
  | {
      column: string;
      by: string;
      kind: "categorical";
      strength: number;
      highest: { value: string; rate: number; rows: number };
      lowest: { value: string; rate: number; rows: number };
    }
  | {
      column: string;
      by: string;
      kind: "numeric";
      strength: number;
      smd: number;
      mean_when_missing: number;
      mean_when_present: number;
    };

export type TableRelationships = {
  sample_rows: number;
  associations: Association[];
  duplicates: { a: string; b: string; same_rows: number; share: number }[];
  missingness: {
    co_missing: { a: string; b: string; phi: number; both_missing: number }[];
    dependencies: MissingDependency[];
  };
  truncated: Record<string, number>;
};

export type ComparisonCell = {
  name: string;
  original_name: string;
  physical_type: string;
  semantic_type: string;
  kind: string | null;
  missing_pct: number | null;
  distinct: number | null;
  median: number | null;
};

export type Comparison = {
  tables: {
    dataset_id: number;
    label: string;
    row_count: number;
    column_count: number;
  }[];
  columns: {
    key: string;
    label: string;
    in_all: boolean;
    cells: Record<string, ComparisonCell>;
    issues: string[];
  }[];
  issues: { code: string; column: string; message: string }[];
  shared_columns: number;
  total_columns: number;
  stackable: boolean;
};

export type CompareResponse = {
  comparison: Comparison;
  links: Relationship[];
};

export type RelationshipSide = {
  dataset_id: number;
  filename: string;
  table_name: string;
  column: string;
  column_label: string;
  distinct: number;
  coverage: number;
};

export type Relationship = {
  id: number;
  left: RelationshipSide;
  right: RelationshipSide;
  shared_values: number;
  cardinality: string;
  name_match: boolean;
};

export type DatasetProfile = {
  dataset: Dataset;
  table: TableProfile | null;
  warnings: DataWarning[];
  columns: Column[];
};

export type Chat = { id: number; title: string; created_at: string };

export type ChartSpec = {
  id: number;
  query_id: number;
  type: "bar" | "line" | "scatter";
  title: string;
  x: string;
  y: string[];
  data: Record<string, string | number | null>[];
  truncated: boolean;
};

export type AgentStep = {
  tool: string;
  args: Record<string, unknown>;
  summary: string;
  error?: string;
  query_id?: number;
  result?: Record<string, unknown>;
};

export type ChatQuery = {
  id: number;
  sql: string;
  row_count: number | null;
  duration_ms: number | null;
  error: string | null;
  columns: string[];
  rows: unknown[][];
};

export type MessageKind =
  "answer" | "clarification" | "cannot_answer" | "error" | "pending";

export type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  kind: MessageKind | null;
  charts: ChartSpec[];
  steps: AgentStep[];
  queries: ChatQuery[];
  grounding: { ok: boolean; checked: number; unsupported: string[] } | null;
  usage: {
    llm_calls: number;
    tool_calls: number;
    tokens: number;
    cost_usd: string;
    sql_errors: number;
    grounding_retries: number;
    duration_ms: number;
  } | null;
  stopped: "tool_calls" | "sql_errors" | "tokens" | "time" | null;
};

export type ChatDetail = { chat: Chat; messages: ChatMessage[] };

/** Server-sent events from POST /projects/{id}/chats/{chatId}/messages. */
export type ChatEvent =
  | { type: "accepted"; user_message_id: number; id: number }
  | { type: "status"; text: string }
  | { type: "step"; step: AgentStep }
  | { type: "done"; message: ChatMessage };

// Research-question fit (apps/api/routes/rqs.py, apps/api/rq/schemas.py)

export type Verdict = "answerable" | "partial" | "not_answerable";
export type RuleLevel = "fail" | "warn" | "info" | "pass";
export type Role = "dependent" | "independent" | "covariate";
export type MatchType = "direct" | "proxy" | "derivable";

export type Candidate = {
  table: string;
  column: string | null;
  expression: string | null;
  match: MatchType;
  kind: string | null;
  justification: string;
};

export type MappedConstruct = {
  name: string;
  role: Role;
  candidates: Candidate[];
  status: "proposed" | "confirmed" | "rejected";
};

export type RQMapping = {
  constructs: MappedConstruct[];
  population_filter: string | null;
  time_column: string | null;
  time_start: string | null;
  time_end: string | null;
  notes: string;
};

export type RQParsed = {
  type:
    "descriptive" | "comparative" | "correlational" | "predictive" | "causal";
  population: string;
  constructs: { name: string; role: Role; description: string }[];
  comparison: string | null;
  time_scope: string | null;
};

export type RuleResult = {
  rule: string;
  level: RuleLevel;
  message: string;
  query_id: number | null;
};

export type RQFact = { fact: string; message: string; query_id: number | null };

export type RQQuery = {
  id: number;
  sql: string;
  row_count: number | null;
  duration_ms: number | null;
  error: string | null;
  result_preview_json: { columns: string[]; rows: unknown[][] } | null;
};

export type RQAssessment = {
  id: number;
  verdict: Verdict;
  explanation: string | null;
  rewording: string | null;
  suggested_method: string | null;
  threats: string[];
  rules: RuleResult[];
  facts: RQFact[];
  gaps: { construct: string; role: Role }[];
  problems: string[];
  grounding: { ok: boolean; checked: number; unsupported: string[] } | null;
  explained_by: "llm" | "rules" | null;
  config_version: string;
  created_at: string;
  queries: RQQuery[];
};

export type ResearchQuestion = {
  id: number;
  text: string;
  position: number;
  status: "queued" | "running" | "done" | "failed";
  error: string | null;
  parsed: RQParsed | null;
  mapping: RQMapping | null;
  assessment: RQAssessment | null;
  created_at: string;
};

export type RQSuggestion = {
  text: string;
  type: string;
  columns: string[];
  reason: string;
};

export type ColumnOption = {
  table: string;
  column: string;
  label: string;
  type: string | null;
};

export type ResearchQuestions = {
  questions: ResearchQuestion[];
  columns: ColumnOption[];
  suggestions: RQSuggestion[] | null;
  suggestions_status: "running" | "done" | "failed" | null;
  suggestions_error: string | null;
};

// Insights (apps/api/routes/insights.py)

export type InsightStatus = "finding" | "weak" | "no_evidence" | "data_quality";

export type ConfounderCheck = {
  column: string;
  verdict: "holds" | "weakens" | "reverses";
  strata: { value: string; n: number; effect: number }[];
};

export type Insight = {
  id: number;
  rq_id: number | null;
  kind: "analysis" | "data_quality";
  status: InsightStatus | null;
  title: string;
  statement: string;
  effect_size: number | null;
  p_value: number | null;
  p_adjusted: number | null;
  score: number | null;
  result: {
    test?: string;
    effect_size_name?: string;
    n?: number;
    magnitude?: string;
    confounders?: ConfounderCheck[];
  } | null;
  chart: ChartSpec | null;
  caveats: string[];
  spec: {
    table: string;
    test: string;
    x: string;
    y: string;
    where: string | null;
    source: string;
  } | null;
  grounding: { ok: boolean; checked: number; unsupported: string[] } | null;
  written_by: "template" | "llm" | null;
  queries: RQQuery[];
};

export type InsightRun = {
  id: number;
  status: "queued" | "running" | "done" | "failed";
  error: string | null;
  planned: number | null;
  failed_json: string[] | null;
  dropped_json: string[] | null;
  used_llm: boolean;
  config_version: string | null;
  created_at: string;
};

export type Insights = { run: InsightRun | null; insights: Insight[] };
