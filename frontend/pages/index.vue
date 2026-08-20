<script setup lang="ts">
import type { Stats } from '~/types/api'

const { api } = useApi()
const stats = ref<Stats>({ sites: 0, pages: 0, content_blocks: 0, similarity_checks: 0 })
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    stats.value = await api<Stats>('/stats')
  } catch (err) {
    error.value = err instanceof Error ? err.message : '无法读取统计数据'
  } finally {
    loading.value = false
  }
})

const statCards = computed(() => [
  { label: '已接入网站', value: stats.value.sites, unit: '个', tone: 'violet' },
  { label: '已采集页面', value: stats.value.pages, unit: '页', tone: 'cyan' },
  { label: '文案内容块', value: stats.value.content_blocks, unit: '条', tone: 'amber' },
  { label: '累计检测', value: stats.value.similarity_checks, unit: '次', tone: 'green' },
])
</script>

<template>
  <section class="page-wrap dashboard-page">
    <div class="hero-grid">
      <div class="hero-copy">
        <span class="eyebrow"><i /> 站群内容防重复工作台</span>
        <h1>让每一个新网站，<br><em>都有自己的表达。</em></h1>
        <p>统一采集历史站群文案，以字面与语义双重检测识别重复风险，在上线前找到内容撞车。</p>
        <div class="hero-actions">
          <NuxtLink to="/checker" class="button primary">开始检测 <span>→</span></NuxtLink>
          <NuxtLink to="/sites" class="button ghost">添加网站</NuxtLink>
        </div>
      </div>
      <div class="score-orbit" aria-hidden="true">
        <div class="orbit orbit-one" />
        <div class="orbit orbit-two" />
        <div class="score-core">
          <span class="score-label">智能检测</span>
          <strong>3<small>重</small></strong>
          <span class="score-note">Hash · 字面 · 语义</span>
        </div>
        <span class="orbit-chip chip-one">精准溯源</span>
        <span class="orbit-chip chip-two">重复高亮</span>
        <span class="orbit-chip chip-three">化学字段降权</span>
      </div>
    </div>

    <p v-if="error" class="alert error">{{ error }}</p>
    <div class="stat-grid" :class="{ loading }">
      <article v-for="card in statCards" :key="card.label" :class="['stat-card', card.tone]">
        <span class="stat-label">{{ card.label }}</span>
        <div><strong>{{ loading ? '—' : card.value.toLocaleString() }}</strong><small>{{ card.unit }}</small></div>
      </article>
    </div>

    <div class="section-heading">
      <div><span class="eyebrow muted">工作流程</span><h2>从采集到检测，只需三步</h2></div>
      <p>真实数据进入数据库，检测结果可直接追溯到原始页面。</p>
    </div>
    <div class="workflow-grid">
      <article><span class="step-number">01</span><h3>接入网站</h3><p>登记域名与 Sitemap，系统验证目标后开始采集。</p><NuxtLink to="/sites">管理网站 →</NuxtLink></article>
      <article><span class="step-number">02</span><h3>沉淀文案</h3><p>过滤导航页脚，按标题和正文段落拆分并向量化。</p><NuxtLink to="/library">浏览文案库 →</NuxtLink></article>
      <article class="featured"><span class="step-number">03</span><h3>上线前检测</h3><p>粘贴新文案，查看 Top 10 风险片段、评分和来源。</p><NuxtLink to="/checker">立即检测 →</NuxtLink></article>
    </div>
  </section>
</template>

