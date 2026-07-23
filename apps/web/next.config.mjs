/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // The Tauri desktop shell's webview loads this same
  // http://127.0.0.1:3000 URL (apps/web/src-tauri/tauri.conf.json's
  // devUrl), but Next.js's dev server blocks cross-origin requests to its
  // own dev assets (webpack-hmr, JS chunks) by default as a DNS-rebinding
  // protection, and sees the webview's requests as a different origin than
  // a plain browser tab would. Left un-whitelisted, this silently breaks
  // all client-side JS inside the desktop shell - the page paints but
  // nothing is clickable, since React never finishes hydrating. Doesn't
  // affect the plain-browser path at all.
  allowedDevOrigins: ['127.0.0.1', 'localhost'],
  async headers() {
    return [{
      source: '/(.*)',
      headers: [
        { key: 'X-Content-Type-Options', value: 'nosniff' },
        { key: 'X-Frame-Options', value: 'DENY' },
        { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' }
      ]
    }]
  }
}
export default nextConfig
