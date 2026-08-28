<script setup lang="ts">
import type { ContentBlockPage, Site } from '~/types/api'

const { api } = useApi()
const sites = ref<Site[]>([])
const data = ref<ContentBlockPage>({ items: [], total: 0, page: 1, page_size: 20, pages: 0 })
const loading = ref(true)
const error = ref('')
const filters = reactive({ site_id: '', keyword: '', page: 1 })
const expanded = ref<Set<number>>(new Set())

const typeLabels: Record<string, string> = { title: '页面标题', meta_description: 'Meta 描述', h1: 'H1', h2: 'H2', h3: 'H3', paragraph: '正文' }

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [siteList, blocks] = await Promise.all([
      sites.value.length ? Promise.resolve(sites.value) : api<Site[]>('/sites'),
      api<ContentBlockPage>('/content-blocks', { query: { site_id: filters.site_id || undefined, keyword: filters.keyword || undefined, page: filters.page, page_size: 20 } }),
    ])
    sites.value = siteList
    data.value = blocks
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载失败'
  } finally {
    loading.value = false
  }
}

function search() { filters.page = 1; load() }
function changePage(page: number) { filters.page = page; load(); window.scrollTo({ top: 0, behavior: 'smooth' }) }
function toggle(id: number) {
  const next = new Set(expanded.value)
  next.has(id) ? next.delete(id) : next.add(id)
  expanded.value = next
}
function formatDate(value: string) { return new Date(value).toLocaleString('zh-CN', { hour12: false }) }
function host(url: string) { try { return new URL(url).hostname } catch { return url } }

onMounted(load)
</script>

<template>
  <section class="page-wrap">
    <div class="page-header"><div><span class="eyebrow muted">内容资产</span><h1>文案库</h1><p>检索所有采集并拆分后的真实站群文案。</p></div><div class="header-count"><strong>{{ data.total.toLocaleString() }}</strong><span>条文案</span></div></div>

    <form class="filter-bar panel" @submit.prevent="search">
      <label class="search-field"><span class="search-symbol">⌕</span><input v-model="filters.keyword" placeholder="搜索文案内容或页面标题"></label>
      <label><select v-model="filters.site_id" @change="search"><option value="">全部网站</option><option v-for="site in sites" :key="site.id" :value="String(site.id)">{{ site.name }}</option></select></label>
      <button class="button primary" type="submit">搜索</button>
    </form>

    <p v-if="error" class="alert error">{{ error }}</p>
    <div class="panel library-panel">
      <div v-if="loading" class="empty-state"><span class="loader" /><p>正在加载文案…</p></div>
      <div v-else-if="!data.items.length" class="empty-state"><span class="empty-icon">库</span><h3>没有找到文案</h3><p>请调整筛选条件，或先到网站管理执行采集。</p><NuxtLink to="/sites" class="button primary">去采集网站</NuxtLink></div>
      <div v-else class="block-list">
        <article v-for="block in data.items" :key="block.id" class="block-row">
          <div class="block-meta"><span class="content-type">{{ typeLabels[block.content_type] || block.content_type }}</span><span>{{ block.site_name }}</span><span>·</span><span>{{ formatDate(block.collected_at) }}</span></div>
          <h3>{{ block.page_title || '无页面标题' }}</h3>
          <p :class="['block-copy', { expanded: expanded.has(block.id) }]">{{ block.original_content }}</p>
          <div class="block-footer"><a :href="block.url" target="_blank" rel="noreferrer">{{ host(block.url) }} <span>↗</span></a><button v-if="block.original_content.length > 150" class="text-button" @click="toggle(block.id)">{{ expanded.has(block.id) ? '收起' : '查看全文' }}</button></div>
        </article>
      </div>
    </div>

    <div v-if="data.pages > 1" class="pagination"><button :disabled="filters.page <= 1" @click="changePage(filters.page - 1)">上一页</button><span>第 {{ filters.page }} / {{ data.pages }} 页</span><button :disabled="filters.page >= data.pages" @click="changePage(filters.page + 1)">下一页</button></div>
  </section>
</template>

