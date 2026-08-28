export interface Site {
  id: number
  name: string
  domain: string
  sitemap_url: string
  site_scheme: 'http' | 'https'
  site_type: 'baseline' | 'candidate'
  include_patterns: string[]
  exclude_patterns: string[]
  allowed_query_params: string[]
  crawler_max_pages: number | null
  request_delay_ms: number
  min_crawl_coverage: number
  status: 'active' | 'paused' | 'error'
  last_crawled_at: string | null
  created_at: string
  page_count: number
  block_count: number
  outdated_block_count: number
}

export interface Stats {
  sites: number
  pages: number
  content_blocks: number
  similarity_checks: number
}

export interface CrawlSummary {
  site_id: number
  pages_discovered: number
  pages_crawled: number
  pages_skipped: number
  blocks_saved: number
  errors: string[]
  previous_pages: number
  retained_pages: number
  stale_pages: number
  prune_blocked: boolean
  coverage: number
}

export interface CrawlPreviewSkipped {
  url: string
  reason: string
}

export interface CrawlPreview {
  site_id: number
  pages_discovered: number
  pages_to_crawl: number
  urls_to_crawl: string[]
  skipped: CrawlPreviewSkipped[]
  errors: string[]
}

export interface CrawlRun {
  id: number
  site_id: number
  status: 'running' | 'completed' | 'completed_with_warnings' | 'error'
  pages_discovered: number
  pages_crawled: number
  pages_skipped: number
  previous_pages: number
  retained_pages: number
  stale_pages: number
  prune_blocked: boolean
  errors: string[]
  started_at: string
  finished_at: string | null
}

export interface BackgroundJob<T = Record<string, unknown>> {
  id: number
  site_id: number
  job_type: 'crawl' | 'preview' | 'audit' | 'reindex'
  status: 'queued' | 'running' | 'completed' | 'error'
  progress: number
  result: T | null
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface ReindexResult {
  site_id: number
  site_name: string
  blocks_reindexed: number
  embedding_version: string
}

export interface SiteAuditFinding {
  candidate_block_id: number
  candidate_content: string
  candidate_content_type: string
  candidate_page_title: string | null
  candidate_url: string
  top_score: number
  risk_level: 'high' | 'medium' | 'low'
  matches: SimilarityResult[]
}

export interface SiteAuditReport {
  site_id: number
  site_name: string
  total_blocks: number
  matched_blocks: number
  high_risk_blocks: number
  medium_risk_blocks: number
  low_risk_blocks: number
  max_similarity: number
  findings: SiteAuditFinding[]
}

export interface ContentBlock {
  id: number
  site_id: number
  site_name: string
  page_id: number
  page_title: string | null
  url: string
  content_type: string
  original_content: string
  collected_at: string
}

export interface ContentBlockPage {
  items: ContentBlock[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface HighlightSegment {
  text: string
  matched: boolean
}

export interface SimilarityResult {
  content_block_id: number
  overall_similarity: number
  risk_level: 'high' | 'medium' | 'low'
  original_content: string
  highlight_segments: HighlightSegment[]
  site_id: number
  site_name: string
  page_title: string | null
  url: string
  content_type: string
  lexical_similarity: number
  semantic_similarity: number
  exact_match: boolean
  chemical_ratio: number
}

export interface SimilarityResponse {
  check_id: number
  result_count: number
  threshold: number
  results: SimilarityResult[]
}
