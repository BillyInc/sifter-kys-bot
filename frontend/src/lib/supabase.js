import { createClient } from '@supabase/supabase-js'
import { authLogger } from './logger'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

// Validate Supabase configuration
const isValidUrl = (url) => {
  if (!url) return false
  try {
    const parsed = new URL(url)
    return parsed.hostname.endsWith('.supabase.co')
  } catch {
    return false
  }
}

// Supports both new publishable keys (sb_publishable_...) and legacy JWT keys (eyJ...)
const isValidKey = (key) => {
  if (!key) return false
  return key.startsWith('sb_publishable_') || key.startsWith('eyJ')
}

export const isSupabaseConfigured = isValidUrl(supabaseUrl) && isValidKey(supabaseAnonKey)

if (!supabaseUrl || !supabaseAnonKey) {
  authLogger.error('Supabase credentials not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in .env')
} else if (!isValidUrl(supabaseUrl)) {
  authLogger.error(`Invalid VITE_SUPABASE_URL: "${supabaseUrl}". Expected format: https://your-project.supabase.co`)
} else if (!isValidKey(supabaseAnonKey)) {
  authLogger.error(`Invalid VITE_SUPABASE_ANON_KEY. Expected sb_publishable_... or legacy JWT key (eyJ...)`)
} else {
  authLogger.debug('Supabase configured successfully', { url: supabaseUrl })
}

if (!isSupabaseConfigured) {
  authLogger.error('Supabase client will not work. Check your .env file and restart the dev server.')
}

export const supabase = createClient(
  supabaseUrl,
  supabaseAnonKey,
  {
    auth: {
      autoRefreshToken: true,
      persistSession: true,
      detectSessionInUrl: true,
    },
  }
)
