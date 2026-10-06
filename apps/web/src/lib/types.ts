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
