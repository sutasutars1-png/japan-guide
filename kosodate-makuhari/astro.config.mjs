import { defineConfig } from 'astro/config';
// 静的ビルド。API は Cloudflare Pages Functions(/functions) が別途処理する。
// site は正規URL(canonical)と /sitemap.xml の生成に使用。独自ドメインに合わせる。
export default defineConfig({
  output: 'static',
  site: 'https://dokoiko.aipress-lab.com',
});
