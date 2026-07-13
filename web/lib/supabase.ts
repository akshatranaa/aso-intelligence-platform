/**
 * Browser Supabase client — used only for authentication (sign in/up/out and
 * reading the current session token). All app data still goes through the
 * same-origin /api proxy, never directly to Supabase.
 *
 * Env (public, safe to expose): NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY.
 */
import { createClient } from "@supabase/supabase-js";

export const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL || "https://placeholder.supabase.co",
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "placeholder-anon-key"
);
