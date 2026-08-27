import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

// Content globs are resolved against the current working directory, which
// is not always `frontend/` (an IDE or launcher may start the dev server
// from the repo root). Anchoring them to this file's location keeps class
// detection working no matter how the server is started.
const here = dirname(fileURLToPath(import.meta.url))

/** @type {import('tailwindcss').Config} */

// NOTE ON VERSION: this project pins Tailwind v3.
// Tailwind v4 moved configuration into CSS and dropped this file. v3 is
// chosen deliberately -- far more tutorials and Stack Overflow answers
// exist for it, which matters when you are learning. Upgrading later is a
// contained job touching only this file and globals.css.

export default {
  content: [resolve(here, 'index.html'), resolve(here, 'src/**/*.{js,ts,jsx,tsx}')],
  theme: {
    extend: {
      colors: {
        // The fire palette. Used for accents, never for large surfaces --
        // a wall of orange reads as a warning, not as a brand.
        fire: {
          50: '#fff7ed',
          100: '#ffedd5',
          200: '#fed7aa',
          300: '#fdba74',
          400: '#fb923c',
          500: '#f97316',
          600: '#ea580c',
          700: '#c2410c',
          800: '#9a3412',
          900: '#7c2d12',
          950: '#431407',
        },
        // Dark neutrals. Slightly warm so they sit next to the orange
        // without looking like two unrelated designs.
        coal: {
          50: '#f6f6f7',
          100: '#e2e2e5',
          200: '#c5c5cb',
          300: '#a0a0a9',
          400: '#7b7b86',
          500: '#61616b',
          600: '#4c4c55',
          700: '#3e3e45',
          800: '#26262b',
          850: '#1c1c20',
          900: '#141417',
          950: '#0b0b0d',
        },
        ember: '#ff6b1a',
        ash: '#8a8a94',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['JetBrains Mono', 'Consolas', 'Monaco', 'monospace'],
      },
      boxShadow: {
        // Used sparingly -- glow on interactive/active elements only.
        glow: '0 0 20px -4px rgba(249, 115, 22, 0.45)',
        'glow-lg': '0 0 45px -8px rgba(249, 115, 22, 0.55)',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        float: 'float 6s ease-in-out infinite',
        'float-slow': 'float 11s ease-in-out infinite',
        'fade-up': 'fadeUp 0.5s ease-out both',
        'scale-in': 'scaleIn 0.16s ease-out both',
      },
      keyframes: {
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-8px)' },
        },
        fadeUp: {
          '0%': { opacity: '0', transform: 'translateY(12px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        // Dropdowns grow from their corner rather than appearing abruptly.
        scaleIn: {
          '0%': { opacity: '0', transform: 'scale(0.96) translateY(-4px)' },
          '100%': { opacity: '1', transform: 'scale(1) translateY(0)' },
        },
      },
    },
  },
  plugins: [],
}
