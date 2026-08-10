import spots from '../../data/spots.json';
import { FEATURES } from '../cats.js';

const SITE = 'https://dokoiko.aipress-lab.com';

export async function GET() {
  const paths = [
    '/', '/spots', '/plan', '/features', '/about', '/legal',
    ...FEATURES.map(f => `/features/${f.slug}`),
    ...spots.map(s => `/spots/${s.id}`),
  ];
  const body = `<?xml version="1.0" encoding="UTF-8"?>\n`
    + `<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n`
    + paths.map(p => `  <url><loc>${SITE}${p}</loc></url>`).join('\n')
    + `\n</urlset>\n`;
  return new Response(body, { headers: { 'content-type': 'application/xml; charset=utf-8' } });
}
