import { defineConfig } from 'astro/config';
// 静的ビルド。API は Cloudflare Pages Functions(/functions) が別途処理する。
export default defineConfig({ output: 'static', site: 'https://example.pages.dev' });
