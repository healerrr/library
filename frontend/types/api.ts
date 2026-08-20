export interface Site {
  id: number
  name: string
  domain: string
  sitemap_url: string
  status: 'active' | 'paused' | 'error'
  last_crawled_at: string | null
  created_at: string
  page_count: number
  block_count: number
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
  blocks_saved: number
  errors: string[]
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

