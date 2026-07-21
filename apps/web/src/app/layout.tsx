import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'InMyAI — Local AI Workspace',
  description: 'Small models. Right context. Real local work.'
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body>{children}</body></html>
}
