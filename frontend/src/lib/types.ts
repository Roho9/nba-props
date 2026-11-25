export type Severity = "exclude" | "caution" | "gate";
export interface Flag { code: string; severity: Severity; text: string }

export interface SlateRow {
  game_id: string; athlete_id: string; athlete_name: string; team: string; opp: string; matchup: string;
  market: string; market_label: string; line: number; side: string; kind: string; book: string; american: number;
  open_line?: number | null; open_american?: number | null; first_seen_american?: number | null;
  p_model?: number | null; p_empirical?: number | null; p_final?: number | null; p_conservative?: number | null;
  p_sd?: number | null; p_market_novig?: number | null; break_even?: number | null; ev?: number | null;
  ev_conservative?: number | null; edge_vs_market?: number | null; risk: string; status: string; reasons: Flag[];
  projection_mean?: number | null; minutes_proj?: number | null; side_verification?: string; retrieved_at?: string;
  game_start: string; model_disagreement?: number | null; fair_american?: number | null; source?: string;
}

export interface Window { n: number; mean: number; median: number; sd: number; iqr: [number, number]; min: number; max: number; hit_rate_vs_line: number; hits: number }
export interface GameRow { date: string; opp: string; home: boolean; minutes: number; value: number | null; pts: number; reb: number; ast: number; fg3m: number; stl: number; blk: number; tov: number; starter: boolean; usage_proxy: number; hit: boolean | null }
export interface Scenario { code: string; label: string; p: number; delta: number; ev: number }

export interface Candidate extends SlateRow {
  rank: number; p_interval: [number, number]; p_push: number; overround?: number | null; blend_weight: number;
  outlier_dependence?: number | null; prediction_id?: number;
  history: {
    windows: Record<string, Window>;
    current_season: { n: number; mean: number; median: number; sd: number; ci95_mean: [number, number]; skew: number; hit_rate_vs_line: number } | null;
    previous_season: { n: number; mean: number; median: number; sd: number; hit_rate_vs_line: number } | null;
    games: GameRow[];
    home_away: Record<string, { n: number; mean: number | null; hit_rate_vs_line: number | null }>;
    vs_opponent: { n: number; mean: number | null; values: number[]; note: string };
  };
  distribution: { mean: number; median: number; p10: number; p90: number; pmf: number[] };
  diagnostics: Record<string, unknown>;
  context: {
    home: boolean; spread_for_team: number | null; game_total: number | null; implied_team_total: number | null; back_to_back: boolean;
    team_pace: number | null; opp_pace: number | null; expected_possessions: number | null;
    opponent: Record<string, number> | null; team: Record<string, number> | null;
    team_injuries: { name: string; status: string; comment: string }[]; opp_injuries: { name: string; status: string; comment: string }[];
    known_out_teammates: string[];
  };
  stress: { scenarios: Scenario[]; worst_p: number; most_sensitive: string[]; n_scenarios_below_break_even: number };
  market_compare: SlateRow[];
  shared_risk: string[];
  sources: { label: string; url: string; retrieved_at: string | null }[];
  explanation: { thesis: string; supporting: string[]; contradicting: string[]; uncertainties: string[]; invalidators: string[]; generator: string };
}

export interface Overview {
  slate_date: string; timezone: string; generated_at: string; run_id: number; n_games: number; n_games_evaluated: number;
  n_players: number; n_props: number; n_offers: number; n_qualifying: number; n_passed_filters: number; books: string[];
  odds_freshest: string | null; odds_oldest: string | null; injury_report_at: string | null; injury_source: string;
  last_successful_run: string | null;
  validation: { validated: boolean; reason: string; blend_weight: number; min_edge: number; report_generated_at: string | null };
  headline: string | null; rejection_counts: Record<string, number>;
  coverage: { game_id: string; matchup: string; start: string; status: string; spread_home: number | null; total: number | null; evaluated: boolean; main_props: number; alt_props: number; players: number; books: string[] }[];
  missing_coverage: string[]; paper_mode: boolean; model_version: string;
  recent_fetch_failures: { source: string; status: number; url: string; at: string }[];
}

export interface SlateResponse {
  overview: Overview | null; candidates: Candidate[]; slate: SlateRow[]; is_today?: boolean; today?: string;
  pipeline: { running: boolean; last_error: string | null; last_started: string | null }; message?: string;
}
