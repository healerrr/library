<script setup lang="ts">
import type { SimilarityResponse, SimilarityResult } from '~/types/api'

const { api } = useApi()
const content = ref('')
const checking = ref(false)
const error = ref('')
const response = ref<SimilarityResponse | null>(null)
const checked = ref(false)

const normalizedLength = computed(() => content.value.replace(/\s/g, '').length)
const overallRisk = computed(() => {
  const score = response.value?.results[0]?.overall_similarity || 0
  if (score >= 0.9) return { label: '高风险', tone: 'high' }
  if (score >= 0.75) return { label: '中风险', tone: 'medium' }
  if (score >= 0.6) return { label: '低风险', tone: 'low' }
  return { label: '未发现风险', tone: 'safe' }
})

async function runCheck() {
  if (normalizedLength.value < 3) { error.value = '请至少输入 3 个有效字符'; return }
  checking.value = true
  error.value = ''
  checked.value = false
  try {
    response.value = await api<SimilarityResponse>('/similarity/check', { method: 'POST', body: { content: content.value, limit: 10 } })
    checked.value = true
  } catch (err) {
    error.value = err instanceof Error ? err.message : '检测失败'
  } finally {
    checking.value = false
  }
}

function percent(value: number) { return `${Math.round(value * 100)}%` }
function riskName(value: SimilarityResult['risk_level']) { return { high: '高风险', medium: '中风险', low: '低风险' }[value] }
function fillExample() { content.value = '在这里粘贴准备上线的新网站文案，系统会从历史文案库中检索字面重复和语义相似内容，并返回可追溯的来源页面。' }
</script>

<template>
  <section class="page-wrap checker-page">
    <div class="page-header"><div><span class="eyebrow muted">上线前检查</span><h1>文案相似度检测</h1><p>综合 Hash、中文 3-gram 与语义向量，返回最高风险的 10 条历史文案。</p></div><div class="risk-legend"><span class="high">≥90%</span><span class="medium">75–90%</span><span class="low">60–75%</span></div></div>

    <div class="checker-layout">
      <div class="panel input-panel">
        <div class="panel-title"><div><h2>待检测文案</h2><p>建议输入一个完整标题或段落</p></div><button class="text-button" type="button" @click="fillExample">填入示例</button></div>
        <textarea v-model="content" maxlength="20000" placeholder="粘贴准备发布的新文案…" @keydown.ctrl.enter="runCheck" />
        <div class="input-foot"><span>{{ normalizedLength.toLocaleString() }} 字符 · Ctrl + Enter 快速检测</span><button class="button primary large" :disabled="checking || normalizedLength < 3" @click="runCheck"><span v-if="checking" class="mini-loader" />{{ checking ? '正在比对…' : '开始检测' }}</button></div>
        <p v-if="error" class="alert error compact">{{ error }}</p>
        <div class="privacy-note"><span>✓</span><p><strong>化学字段智能降权</strong>CAS 号、分子式、分子量、规格参数不会单独触发高风险。</p></div>
      </div>

      <aside class="panel methodology">
        <span class="eyebrow muted">评分构成</span><h2>多策略交叉判断</h2>
        <div class="method-item"><span>01</span><div><strong>完全重复</strong><p>标准化后 SHA-256 Hash 精确命中</p></div></div>
        <div class="method-item"><span>02</span><div><strong>字面相似</strong><p>中文字符 3-gram Jaccard</p></div></div>
        <div class="method-item"><span>03</span><div><strong>语义相似</strong><p>中文 Embedding 余弦距离</p></div></div>
        <p class="method-note">只展示综合相似度 ≥ 60% 的结果</p>
      </aside>
    </div>

    <section v-if="checked" class="results-section">
      <div class="result-summary"><div><span :class="['risk-orb', overallRisk.tone]">{{ response?.results.length ? percent(response.results[0].overall_similarity) : '✓' }}</span><div><span class="eyebrow muted">检测完成</span><h2>{{ overallRisk.label }}</h2><p>在历史库中找到 {{ response?.result_count || 0 }} 条达到展示阈值的内容</p></div></div><button class="button ghost" @click="response = null; checked = false">检测新文案</button></div>

      <div v-if="!response?.results.length" class="panel empty-state safe-state"><span class="empty-icon">✓</span><h3>没有发现明显重复</h3><p>当前文案与历史库内容的综合相似度均低于 60%。</p></div>
      <div v-else class="result-list">
        <article v-for="(result, index) in response.results" :key="result.content_block_id" class="panel result-card">
          <div class="result-rank"><span>#{{ index + 1 }}</span><strong>{{ percent(result.overall_similarity) }}</strong><small>综合相似度</small></div>
          <div class="result-main">
            <div class="result-head"><div><span :class="['risk-tag', result.risk_level]">{{ riskName(result.risk_level) }}</span><span v-if="result.exact_match" class="exact-tag">Hash 完全命中</span><span class="type-tag">{{ result.content_type }}</span></div><a :href="result.url" target="_blank" rel="noreferrer">查看原页 ↗</a></div>
            <p class="highlight-copy"><template v-for="(segment, i) in result.highlight_segments" :key="i"><mark v-if="segment.matched">{{ segment.text }}</mark><template v-else>{{ segment.text }}</template></template></p>
            <div class="source-line"><strong>{{ result.site_name }}</strong><span>{{ result.page_title || '无页面标题' }}</span></div>
            <div class="score-bars"><div><span>字面相似 <b>{{ percent(result.lexical_similarity) }}</b></span><i><em :style="{ width: percent(result.lexical_similarity) }" /></i></div><div><span>语义相似 <b>{{ percent(result.semantic_similarity) }}</b></span><i><em :style="{ width: percent(result.semantic_similarity) }" /></i></div></div>
          </div>
        </article>
      </div>
    </section>
  </section>
</template>

