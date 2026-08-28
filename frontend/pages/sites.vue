<script setup lang="ts">
import type { BackgroundJob, CrawlPreview, CrawlRun, CrawlSummary, ReindexResult, Site, SiteAuditReport } from '~/types/api'

const { api } = useApi()
const sites = ref<Site[]>([])
const loading = ref(true)
const saving = ref(false)
const crawlingId = ref<number | null>(null)
const previewingId = ref<number | null>(null)
const auditingId = ref<number | null>(null)
const reindexingId = ref<number | null>(null)
const jobProgress = ref(0)
const auditReport = ref<SiteAuditReport | null>(null)
const previewResult = ref<CrawlPreview | null>(null)
const previewSiteName = ref('')
const crawlRuns = ref<CrawlRun[]>([])
const crawlRunSiteName = ref('')
const loadingRunsId = ref<number | null>(null)
const editingStrategyId = ref<number | null>(null)
const strategySaving = ref(false)
const message = ref<{ type: 'success' | 'error'; text: string } | null>(null)
const showForm = ref(false)
const form = reactive({ name: '', domain: '', site_scheme: 'https', site_type: 'baseline', status: 'active' })
const strategyForm = reactive({
  siteScheme: 'https',
  includePatterns: '',
  excludePatterns: '',
  allowedQueryParams: '',
  crawlerMaxPages: '',
  requestDelayMs: 0,
  minCoveragePercent: 70,
})
const showStrategyModal = ref(false)
const showPreviewModal = ref(false)
const showAuditModal = ref(false)
const showRunsModal = ref(false)
const busy = computed(() => crawlingId.value !== null || previewingId.value !== null || auditingId.value !== null || reindexingId.value !== null)

async function loadSites() {
  loading.value = true
  try {
    sites.value = await api<Site[]>('/sites')
  } catch (err) {
    notify('error', err)
  } finally {
    loading.value = false
  }
}

function notify(type: 'success' | 'error', err: unknown) {
  message.value = { type, text: err instanceof Error ? err.message : String(err) }
  window.setTimeout(() => { message.value = null }, 6000)
}

async function createSite() {
  saving.value = true
  try {
    await api<Site>('/sites', { method: 'POST', body: form })
    Object.assign(form, { name: '', domain: '', site_scheme: 'https', site_type: 'baseline', status: 'active' })
    showForm.value = false
    notify('success', '网站已添加，可以开始采集')
    await loadSites()
  } catch (err) {
    notify('error', err)
  } finally {
    saving.value = false
  }
}

async function crawl(site: Site) {
  crawlingId.value = site.id
  jobProgress.value = 0
  notify('success', `${site.name} 已进入后台采集队列，可以继续使用其他页面`)
  try {
    const initial = await api<BackgroundJob<CrawlSummary>>(`/sites/${site.id}/crawl-jobs`, { method: 'POST' })
    const job = await waitForJob(initial)
    const result = job.result
    if (!result) throw new Error('采集任务没有返回结果')
    const suffix = result.errors.length ? `，${result.errors.length} 个页面失败` : ''
    const skipped = result.pages_skipped ? `，跳过 ${result.pages_skipped} 个产品/动态页面` : ''
    const protection = result.prune_blocked
      ? `。覆盖率仅 ${percent(result.coverage)}，检测到 ${result.stale_pages} 个未访问旧页面，系统已禁止删除并完整保留旧数据`
      : `，覆盖率 ${percent(result.coverage)}`
    notify('success', `采集完成：${result.pages_crawled} 个页面，保存 ${result.blocks_saved} 条文案${skipped}${suffix}${protection}`)
    await loadSites()
  } catch (err) {
    notify('error', err)
    await loadSites()
  } finally {
    crawlingId.value = null
  }
}

async function preview(site: Site) {
  previewingId.value = site.id
  previewResult.value = null
  previewSiteName.value = site.name
  jobProgress.value = 0
  notify('success', `正在预览 ${site.name} 的采集范围，预览不会修改文案库`)
  try {
    const initial = await api<BackgroundJob<CrawlPreview>>(`/sites/${site.id}/preview-jobs`, { method: 'POST' })
    const job = await waitForJob(initial)
    if (!job.result) throw new Error('预览任务没有返回结果')
    previewResult.value = job.result
    showPreviewModal.value = true
    notify('success', `预览完成：发现 ${job.result.pages_discovered} 个链接，其中 ${job.result.pages_to_crawl} 个页面将被采集`)
  } catch (err) {
    notify('error', err)
  } finally {
    previewingId.value = null
  }
}

async function waitForJob<T>(initial: BackgroundJob<T>): Promise<BackgroundJob<T>> {
  let job = initial
  while (job.status === 'queued' || job.status === 'running') {
    jobProgress.value = job.progress
    await new Promise(resolve => window.setTimeout(resolve, 1200))
    job = await api<BackgroundJob<T>>(`/jobs/${job.id}`)
  }
  jobProgress.value = job.progress
  if (job.status === 'error') throw new Error(job.error || '后台任务执行失败')
  return job
}

async function audit(site: Site) {
  auditingId.value = site.id
  auditReport.value = null
  jobProgress.value = 0
  notify('success', `正在后台检测 ${site.name} 的全部文案…`)
  try {
    const initial = await api<BackgroundJob<SiteAuditReport>>(`/sites/${site.id}/audit-jobs`, { method: 'POST' })
    const job = await waitForJob(initial)
    if (!job.result) throw new Error('检测任务没有返回报告')
    auditReport.value = job.result
    showAuditModal.value = true
    notify('success', `整站检测完成：${job.result.matched_blocks} 条文案达到风险阈值`)
  } catch (err) {
    notify('error', err)
  } finally {
    auditingId.value = null
  }
}

async function reindex(site: Site) {
  reindexingId.value = site.id
  jobProgress.value = 0
  notify('success', `正在后台更新 ${site.name} 的语义向量…`)
  try {
    const initial = await api<BackgroundJob<ReindexResult>>(`/sites/${site.id}/reindex-jobs`, { method: 'POST' })
    const job = await waitForJob(initial)
    if (!job.result) throw new Error('向量任务没有返回结果')
    notify('success', `向量更新完成：${job.result.blocks_reindexed} 条文案`)
    await loadSites()
  } catch (err) {
    notify('error', err)
  } finally {
    reindexingId.value = null
  }
}

function percent(value: number) { return `${Math.round(value * 100)}%` }

function splitRuleLines(value: string) {
  return [...new Set(value.split(/\r?\n/).map(item => item.trim()).filter(Boolean))]
}

function splitQueryParams(value: string) {
  return [...new Set(value.split(/[\n,]/).map(item => item.trim()).filter(Boolean))]
}

function openStrategy(site: Site) {
  editingStrategyId.value = site.id
  Object.assign(strategyForm, {
    siteScheme: site.site_scheme,
    includePatterns: site.include_patterns.join('\n'),
    excludePatterns: site.exclude_patterns.join('\n'),
    allowedQueryParams: site.allowed_query_params.join(', '),
    crawlerMaxPages: site.crawler_max_pages?.toString() || '',
    requestDelayMs: site.request_delay_ms,
    minCoveragePercent: Math.round(site.min_crawl_coverage * 100),
  })
  showStrategyModal.value = true
}

async function saveStrategy() {
  if (editingStrategyId.value === null) return
  strategySaving.value = true
  try {
    const pageLimit = strategyForm.crawlerMaxPages.trim()
    await api<Site>(`/sites/${editingStrategyId.value}`, {
      method: 'PATCH',
      body: {
        site_scheme: strategyForm.siteScheme,
        include_patterns: splitRuleLines(strategyForm.includePatterns),
        exclude_patterns: splitRuleLines(strategyForm.excludePatterns),
        allowed_query_params: splitQueryParams(strategyForm.allowedQueryParams),
        crawler_max_pages: pageLimit ? Number.parseInt(pageLimit, 10) : null,
        request_delay_ms: Number(strategyForm.requestDelayMs),
        min_crawl_coverage: Number(strategyForm.minCoveragePercent) / 100,
      },
    })
    notify('success', '采集策略已保存，建议先执行采集预览再正式采集')
    showStrategyModal.value = false
    editingStrategyId.value = null
    await loadSites()
  } catch (err) {
    notify('error', err)
  } finally {
    strategySaving.value = false
  }
}

async function showCrawlRuns(site: Site) {
  loadingRunsId.value = site.id
  crawlRunSiteName.value = site.name
  try {
    crawlRuns.value = await api<CrawlRun[]>(`/sites/${site.id}/crawl-runs?limit=10`)
    showRunsModal.value = true
  } catch (err) {
    notify('error', err)
  } finally {
    loadingRunsId.value = null
  }
}

async function toggleStatus(site: Site) {
  const status = site.status === 'paused' ? 'active' : 'paused'
  try {
    await api<Site>(`/sites/${site.id}`, { method: 'PATCH', body: { status } })
    await loadSites()
  } catch (err) {
    notify('error', err)
  }
}

async function removeSite(site: Site) {
  if (!window.confirm(`删除“${site.name}”及其全部页面和文案？此操作不可撤销。`)) return
  try {
    await api<void>(`/sites/${site.id}`, { method: 'DELETE' })
    notify('success', '网站及相关文案已删除')
    await loadSites()
  } catch (err) {
    notify('error', err)
  }
}

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '尚未采集'
}

onMounted(loadSites)
</script>

<template>
  <section class="page-wrap">
    <div class="page-header">
      <div><span class="eyebrow muted">数据源</span><h1>网站管理</h1><p>登记站点并从首页站内链接采集页面文案。</p></div>
      <button class="button primary" type="button" @click="showForm = !showForm">{{ showForm ? '收起表单' : '+ 添加网站' }}</button>
    </div>

    <Transition name="slide">
      <form v-if="showForm" class="panel site-form" @submit.prevent="createSite">
        <div class="form-heading"><div><h2>接入新网站</h2><p>系统会从网站首页查找同域名内链，不采集友情链接。</p></div><span class="safe-badge">安全域名校验</span></div>
        <div class="form-grid">
          <label><span>网站名称</span><input v-model="form.name" required maxlength="200" placeholder="例如：中文官网"></label>
          <label><span>域名</span><input v-model="form.domain" required placeholder="example.com"></label>
          <label><span>协议</span><select v-model="form.site_scheme"><option value="https">HTTPS</option><option value="http">HTTP</option></select></label>
          <label><span>用途</span><select v-model="form.site_type"><option value="baseline">历史基准站点</option><option value="candidate">待上线检测站点</option></select></label>
          <label><span>状态</span><select v-model="form.status"><option value="active">启用</option><option value="paused">暂停</option></select></label>
        </div>
        <div class="form-actions"><button class="button ghost" type="button" @click="showForm = false">取消</button><button class="button primary" :disabled="saving">{{ saving ? '保存中…' : '保存网站' }}</button></div>
      </form>
    </Transition>

    <div v-if="message" :class="['alert', message.type]">{{ message.text }}</div>

    <div class="panel table-panel">
      <div class="panel-title"><div><h2>已接入网站</h2><p>共 {{ sites.length }} 个数据源</p></div><button class="text-button" :disabled="loading" @click="loadSites">刷新</button></div>
      <div v-if="loading" class="empty-state"><span class="loader" /><p>正在读取网站…</p></div>
      <div v-else-if="!sites.length" class="empty-state"><span class="empty-icon">站</span><h3>还没有接入网站</h3><p>添加第一个网站并执行采集，文案会出现在文案库。</p><button class="button primary" @click="showForm = true">添加网站</button></div>
      <div v-else class="site-list">
        <article v-for="site in sites" :key="site.id" class="site-row">
          <div class="site-identity"><span class="site-avatar">{{ site.name.slice(0, 1) }}</span><div><h3>{{ site.name }} <small :class="['site-type', site.site_type]">{{ site.site_type === 'baseline' ? '历史库' : '待上线' }}</small></h3><a :href="`${site.site_scheme}://${site.domain}`" target="_blank" rel="noreferrer">{{ site.site_scheme }}://{{ site.domain }} ↗</a></div></div>
          <div class="site-metrics"><div><strong>{{ site.page_count }}</strong><span>页面</span></div><div><strong>{{ site.block_count }}</strong><span>文案</span></div></div>
          <div class="crawl-time"><span>最近采集</span><strong>{{ formatDate(site.last_crawled_at) }}</strong></div>
          <span :class="['status-pill', site.status]">{{ site.status === 'active' ? '运行中' : site.status === 'paused' ? '已暂停' : '异常' }}</span>
          <div class="row-actions">
            <button class="button small primary" :disabled="busy" @click="crawl(site)">{{ crawlingId === site.id ? `采集 ${jobProgress}%` : '立即采集' }}</button>
            <button class="button small ghost" :disabled="busy" @click="preview(site)">{{ previewingId === site.id ? `预览 ${jobProgress}%` : '采集预览' }}</button>
            <button v-if="site.site_type === 'candidate'" class="button small ghost" :disabled="busy || !site.block_count" @click="audit(site)">{{ auditingId === site.id ? `检测 ${jobProgress}%` : '整站检测' }}</button>
            <button v-if="site.outdated_block_count" class="button small warning" :disabled="busy" @click="reindex(site)">{{ reindexingId === site.id ? `更新 ${jobProgress}%` : `更新向量 ${site.outdated_block_count}` }}</button>
            <button class="icon-button" title="采集策略" @click="openStrategy(site)">策</button>
            <button class="icon-button" title="采集记录" :disabled="loadingRunsId !== null" @click="showCrawlRuns(site)">{{ loadingRunsId === site.id ? '…' : '录' }}</button>
            <button class="icon-button" :title="site.status === 'paused' ? '启用' : '暂停'" @click="toggleStatus(site)">{{ site.status === 'paused' ? '启' : '停' }}</button>
            <button class="icon-button danger" title="删除" @click="removeSite(site)">删</button>
          </div>
        </article>
      </div>
    </div>

    <div v-if="showStrategyModal && editingStrategyId !== null" class="modal-overlay" @click.self="showStrategyModal = false; editingStrategyId = null">
      <form class="panel app-modal strategy-modal" @submit.prevent="saveStrategy">
        <div class="panel-title">
          <div><span class="eyebrow muted">每站独立配置</span><h2>采集策略</h2><p>正则规则按 URL 路径匹配；首页始终保留，不受包含规则限制。</p></div>
          <button class="modal-close" type="button" @click="showStrategyModal = false; editingStrategyId = null">×</button>
        </div>
        <div class="policy-grid">
          <label><span>采集协议</span><select v-model="strategyForm.siteScheme"><option value="https">HTTPS</option><option value="http">HTTP</option></select></label>
          <label><span>只包含这些路由（每行一条正则，留空表示不限制）</span><textarea v-model="strategyForm.includePatterns" rows="5" placeholder="^/about\n^/news"></textarea></label>
          <label><span>排除这些路由（每行一条正则）</span><textarea v-model="strategyForm.excludePatterns" rows="5" placeholder="^/search\n^/member"></textarea></label>
          <label><span>允许保留的查询参数</span><input v-model="strategyForm.allowedQueryParams" placeholder="例如：page, lang"></label>
          <label><span>最多采集页面（留空使用系统默认值）</span><input v-model="strategyForm.crawlerMaxPages" inputmode="numeric" pattern="[0-9]*" placeholder="例如：300"></label>
          <label><span>请求间隔（毫秒）</span><input v-model.number="strategyForm.requestDelayMs" type="number" min="0" max="5000" step="100"></label>
          <label><span>最低安全覆盖率（10%–100%）</span><input v-model.number="strategyForm.minCoveragePercent" type="number" min="10" max="100" step="1"></label>
        </div>
        <div class="policy-note">正式采集出现请求错误，或本次覆盖率低于这里的阈值时，系统不会清理任何未访问的旧页面。</div>
        <div class="form-actions"><button class="button ghost" type="button" @click="showStrategyModal = false; editingStrategyId = null">取消</button><button class="button primary" :disabled="strategySaving">{{ strategySaving ? '保存中…' : '保存策略' }}</button></div>
      </form>
    </div>

    <div v-if="showPreviewModal && previewResult" class="modal-overlay" @click.self="showPreviewModal = false">
    <section class="panel app-modal result-panel preview-panel">
      <div class="panel-title"><div><span class="eyebrow muted">只读预览</span><h2>{{ previewSiteName }}</h2><p>预览只访问页面并分析路由，不写入页面或文案数据。</p></div><button class="modal-close" @click="showPreviewModal = false">×</button></div>
      <div class="preview-summary"><div><strong>{{ previewResult.pages_discovered }}</strong><span>发现链接</span></div><div><strong>{{ previewResult.pages_to_crawl }}</strong><span>将采集页面</span></div><div><strong>{{ previewResult.skipped.length }}</strong><span>已过滤</span></div><div :class="{ high: previewResult.errors.length }"><strong>{{ previewResult.errors.length }}</strong><span>请求错误</span></div></div>
      <div class="preview-columns">
        <div><h3>将采集的 URL</h3><div v-if="!previewResult.urls_to_crawl.length" class="compact-empty">没有可采集页面</div><ul v-else class="url-list"><li v-for="url in previewResult.urls_to_crawl" :key="url"><a :href="url" target="_blank" rel="noreferrer">{{ url }}</a></li></ul></div>
        <div><h3>过滤结果与原因</h3><div v-if="!previewResult.skipped.length" class="compact-empty">没有过滤链接</div><ul v-else class="url-list skipped-list"><li v-for="item in previewResult.skipped" :key="item.url"><a :href="item.url" target="_blank" rel="noreferrer">{{ item.url }}</a><span>{{ item.reason }}</span></li></ul></div>
      </div>
      <div v-if="previewResult.errors.length" class="preview-errors"><strong>请求错误</strong><p v-for="error in previewResult.errors" :key="error">{{ error }}</p></div>
    </section>
    </div>

    <div v-if="showRunsModal && crawlRunSiteName" class="modal-overlay" @click.self="showRunsModal = false">
    <section class="panel app-modal result-panel run-panel">
      <div class="panel-title"><div><span class="eyebrow muted">最近 10 次</span><h2>{{ crawlRunSiteName }} · 采集记录</h2><p>可追踪每次采集覆盖率、过滤数量和旧数据保护状态。</p></div><button class="modal-close" @click="showRunsModal = false">×</button></div>
      <div v-if="!crawlRuns.length" class="compact-empty">这个网站还没有采集运行记录</div>
      <div v-else class="run-list">
        <article v-for="run in crawlRuns" :key="run.id">
          <div><strong>{{ formatDate(run.started_at) }}</strong><span :class="['run-status', run.prune_blocked ? 'protected' : run.status]">{{ run.prune_blocked ? '旧数据已保护' : run.status === 'completed' ? '正常完成' : run.status === 'running' ? '运行中' : '有警告' }}</span></div>
          <p>发现 {{ run.pages_discovered }} · 采集 {{ run.pages_crawled }} · 跳过 {{ run.pages_skipped }} · 保留 {{ run.retained_pages }}/{{ run.previous_pages }} · 未访问旧页面 {{ run.stale_pages }}</p>
          <small v-if="run.errors.length">{{ run.errors.length }} 个请求错误</small>
        </article>
      </div>
    </section>
    </div>

    <div v-if="showAuditModal && auditReport" class="modal-overlay" @click.self="showAuditModal = false">
    <section class="panel app-modal audit-report">
      <div class="panel-title"><div><span class="eyebrow muted">整站检测报告</span><h2>{{ auditReport.site_name }}</h2><p>共检测 {{ auditReport.total_blocks }} 条文案，自动排除本站内容，仅与历史基准库比较。</p></div><button class="modal-close" @click="showAuditModal = false">×</button></div>
      <div class="audit-summary"><div><strong>{{ percent(auditReport.max_similarity) }}</strong><span>最高相似度</span></div><div class="high"><strong>{{ auditReport.high_risk_blocks }}</strong><span>高风险</span></div><div class="medium"><strong>{{ auditReport.medium_risk_blocks }}</strong><span>中风险</span></div><div><strong>{{ auditReport.low_risk_blocks }}</strong><span>低风险</span></div></div>
      <div v-if="!auditReport.findings.length" class="empty-state safe-state"><span class="empty-icon">✓</span><h3>没有发现明显重复</h3></div>
      <div v-else class="audit-findings">
        <article v-for="finding in auditReport.findings" :key="finding.candidate_block_id">
          <div><span :class="['risk-tag', finding.risk_level]">{{ finding.risk_level === 'high' ? '高风险' : finding.risk_level === 'medium' ? '中风险' : '低风险' }}</span><strong>{{ percent(finding.top_score) }}</strong><a :href="finding.candidate_url" target="_blank" rel="noreferrer">查看待上线页面 ↗</a></div>
          <p>{{ finding.candidate_content }}</p>
          <small v-if="finding.matches[0]">最相似来源：{{ finding.matches[0].site_name }} · {{ finding.matches[0].page_title || '无页面标题' }}</small>
        </article>
      </div>
    </section>
    </div>
  </section>
</template>
