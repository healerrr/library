<script setup lang="ts">
const route = useRoute()
const colorMode = useColorMode()

const navigation = [
  { to: '/', label: '总览', mark: '总' },
  { to: '/sites', label: '网站管理', mark: '站' },
  { to: '/library', label: '文案库', mark: '库' },
  { to: '/checker', label: '相似度检测', mark: '检' },
]

function isActive(path: string) {
  return path === '/' ? route.path === '/' : route.path.startsWith(path)
}

function toggleTheme() {
  colorMode.preference = colorMode.value === 'dark' ? 'light' : 'dark'
}
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <NuxtLink to="/" class="brand">
        <span class="brand-logo">文</span>
        <span>
          <strong>文鉴</strong>
          <small>CopyGuard</small>
        </span>
      </NuxtLink>

      <nav class="main-nav" aria-label="主导航">
        <NuxtLink
          v-for="item in navigation"
          :key="item.to"
          :to="item.to"
          :class="['nav-link', { active: isActive(item.to) }]"
        >
          <span class="nav-mark">{{ item.mark }}</span>
          <span>{{ item.label }}</span>
        </NuxtLink>
      </nav>

      <div class="sidebar-foot">
        <div class="system-state">
          <span class="pulse-dot" />
          <span>系统已就绪</span>
        </div>
        <button class="theme-toggle" type="button" aria-label="切换深浅色" @click="toggleTheme">
          {{ colorMode.value === 'dark' ? '浅色模式' : '深色模式' }}
        </button>
      </div>
    </aside>

    <main class="main-content">
      <header class="mobile-header">
        <NuxtLink to="/" class="brand compact"><span class="brand-logo">文</span><strong>文鉴</strong></NuxtLink>
        <button class="theme-toggle" type="button" @click="toggleTheme">切换主题</button>
      </header>
      <NuxtPage />
    </main>

    <nav class="mobile-nav" aria-label="移动端导航">
      <NuxtLink
        v-for="item in navigation"
        :key="item.to"
        :to="item.to"
        :class="{ active: isActive(item.to) }"
      >
        <span>{{ item.mark }}</span>
        <small>{{ item.label }}</small>
      </NuxtLink>
    </nav>
  </div>
</template>

