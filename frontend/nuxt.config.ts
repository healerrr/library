export default defineNuxtConfig({
  compatibilityDate: '2025-07-15',
  devtools: { enabled: false },
  ssr: false,
  modules: ['@nuxtjs/color-mode'],
  css: ['~/assets/css/main.css'],
  colorMode: {
    preference: 'light',
    fallback: 'light',
    classSuffix: '',
  },
  runtimeConfig: {
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE || '/api',
    },
  },
  routeRules: {
    '/api/**': {
      proxy: `${process.env.NUXT_API_PROXY_TARGET || 'http://127.0.0.1:8001/api'}/**`,
    },
  },
  app: {
    head: {
      htmlAttrs: { lang: 'zh-CN' },
      title: '文鉴 CopyGuard｜站群文案相似度检测',
      meta: [
        { name: 'description', content: '站群文案统一采集、检索与相似度风险检测系统' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
      ],
    },
  },
})
