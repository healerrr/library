interface ApiOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  body?: unknown
  query?: Record<string, string | number | undefined | null>
}

export function useApi() {
  const config = useRuntimeConfig()

  async function api<T>(path: string, options: ApiOptions = {}): Promise<T> {
    try {
      return await $fetch<T>(`${config.public.apiBase}${path}`, {
        method: options.method || 'GET',
        body: options.body,
        query: options.query,
      })
    } catch (error: any) {
      const detail = error?.data?.detail
      if (Array.isArray(detail)) {
        throw new Error(detail.map((item) => item.msg).join('；'))
      }
      throw new Error(detail || error?.message || '请求失败，请稍后重试')
    }
  }

  return { api }
}

