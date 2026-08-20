<script setup lang="ts">
import type { CrawlSummary, Site } from '~/types/api'

const { api } = useApi()
const sites = ref<Site[]>([])
const loading = ref(true)
const saving = ref(false)
const crawlingId = ref<number | null>(null)
const message = ref<{ type: 'success' | 'error'; text: string } | null>(null)
const showForm = ref(false)
const form = reactive({ name: '', domain: '', sitemap_url: '', status: 'active' })

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
    Object.assign(form, { name: '', domain: '', sitemap_url: '', status: 'active' })
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
  notify('success', `正在采集 ${site.name}，页面较多时需要几分钟…`)
  try {
    const result = await api<CrawlSummary>(`/sites/${site.id}/crawl`, { method: 'POST' })
    const suffix = result.errors.length ? `，${result.errors.length} 个页面失败` : ''
    notify('success', `采集完成：${result.pages_crawled} 个页面，保存 ${result.blocks_saved} 条文案${suffix}`)
    await loadSites()
  } catch (err) {
    notify('error', err)
    await loadSites()
  } finally {
    crawlingId.value = null
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
      <div><span class="eyebrow muted">数据源</span><h1>网站管理</h1><p>登记站点并从 Sitemap 采集页面文案。</p></div>
      <button class="button primary" type="button" @click="showForm = !showForm">{{ showForm ? '收起表单' : '+ 添加网站' }}</button>
    </div>

    <Transition name="slide">
      <form v-if="showForm" class="panel site-form" @submit.prevent="createSite">
        <div class="form-heading"><div><h2>接入新网站</h2><p>Sitemap 必须与登记域名相同或属于其子域名。</p></div><span class="safe-badge">安全域名校验</span></div>
        <div class="form-grid">
          <label><span>网站名称</span><input v-model="form.name" required maxlength="200" placeholder="例如：中文官网"></label>
          <label><span>域名</span><input v-model="form.domain" required placeholder="example.com"></label>
          <label class="wide"><span>Sitemap 地址</span><input v-model="form.sitemap_url" type="url" required placeholder="https://example.com/sitemap.xml"></label>
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
          <div class="site-identity"><span class="site-avatar">{{ site.name.slice(0, 1) }}</span><div><h3>{{ site.name }}</h3><a :href="`https://${site.domain}`" target="_blank" rel="noreferrer">{{ site.domain }} ↗</a></div></div>
          <div class="site-metrics"><div><strong>{{ site.page_count }}</strong><span>页面</span></div><div><strong>{{ site.block_count }}</strong><span>文案</span></div></div>
          <div class="crawl-time"><span>最近采集</span><strong>{{ formatDate(site.last_crawled_at) }}</strong></div>
          <span :class="['status-pill', site.status]">{{ site.status === 'active' ? '运行中' : site.status === 'paused' ? '已暂停' : '异常' }}</span>
          <div class="row-actions"><button class="button small primary" :disabled="crawlingId !== null" @click="crawl(site)">{{ crawlingId === site.id ? '采集中…' : '立即采集' }}</button><button class="icon-button" :title="site.status === 'paused' ? '启用' : '暂停'" @click="toggleStatus(site)">{{ site.status === 'paused' ? '启' : '停' }}</button><button class="icon-button danger" title="删除" @click="removeSite(site)">删</button></div>
        </article>
      </div>
    </div>
  </section>
</template>

