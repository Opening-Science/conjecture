import tailwindcss from '@tailwindcss/vite'

const environment = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env ?? {}

export default defineNuxtConfig({
  compatibilityDate: '2026-01-01',
  css: ['~/assets/css/main.css', '~/assets/css/accessibility.css'],
  components: [{ path: '~/components', pathPrefix: false }],
  vite: { plugins: [tailwindcss()] },
  typescript: { strict: true },
  devtools: { enabled: false },
  // /panel/ is the hub's read-only run panel, exported as static files by
  // scripts/hub-data.py, not a Nuxt route
  nitro: { prerender: { crawlLinks: true, ignore: ['/_lab', '/panel'] } },
  // Nuxt discovers pages before prerendering. Remove the lab from production
  // routing as well so neither its pages nor its client chunks can ship.
  hooks: {
    'pages:extend'(pages) {
      if (environment.NODE_ENV === 'development') return
      const removeLab = (items: typeof pages) => {
        for (let i = items.length - 1; i >= 0; i--) {
          const page = items[i]!
          if (page.file?.replaceAll('\\', '/').includes('/pages/_lab/')) items.splice(i, 1)
          else if (page.children) removeLab(page.children)
        }
      }
      removeLab(pages)
    },
  },
  app: { head: { htmlAttrs: { lang: 'en' } } },
})
