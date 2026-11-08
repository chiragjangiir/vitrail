import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      // ── Design System « Mission Control » (refonte aidesigner 2026-07-17) ───
      // DARK ONLY. Tokens en variables CSS (globals.css). La rampe de gris est
      // SÉMANTIQUE (bas = fonds, haut = texte — inversée : 50 sombre → 900 clair),
      // donc les ~1300 classes gray-* du frontend suivent sans édition par écran.
      colors: {
        canvas:        'var(--color-canvas)',   // fond de page (#0B0C10)
        'canvas-dark': '#0B0C10',               // littéral (player/anti-flash)
        surface:       'var(--color-surface)',  // panels/cartes (#151722)
        'surface-hover': 'var(--color-surface-hover)',
        sidebar:       'var(--color-sidebar)',
        // Triplet RGB (+ <alpha-value>) : les modifieurs d'opacité fonctionnent
        // (bg-accent/10, ring-accent/40…) — un hex/var simple les rendait transparents.
        accent:        'rgb(var(--color-accent-rgb) / <alpha-value>)',
        'accent-hover': 'var(--color-accent-hover)',
        // Statuts (tons vifs — fond sombre)
        success:  '#10B981',
        warning:  '#F59E0B',
        danger:   '#EF4444',
        info:     '#3B82F6',
        // Neutres sémantiques (rampe inversée en .dark)
        'gray-50':  'var(--color-gray-50)',
        'gray-100': 'var(--color-gray-100)',
        'gray-200': 'var(--color-gray-200)',
        // 300/500/700 : paliers intermédiaires — sans eux, les classes gray-300/500/700
        // éparses retombaient sur la palette Tailwind par défaut (gris FONCÉS → illisibles
        // sur fond sombre). Interpolés dans la rampe sémantique inversée.
        'gray-300': 'var(--color-gray-300)',
        'gray-400': 'var(--color-gray-400)',
        'gray-500': 'var(--color-gray-500)',
        'gray-600': 'var(--color-gray-600)',
        'gray-700': 'var(--color-gray-700)',
        'gray-800': 'var(--color-gray-800)',
        'gray-900': 'var(--color-gray-900)',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        // ⚠️ `mono` n'était PAS personnalisée : les 35 surfaces `font-mono` (IP, MAC,
        // versions, schémas) tombaient sur la pile par défaut de Tailwind et rendaient
        // donc dans une police DIFFÉRENTE selon l'OS — SF Mono, Consolas, Liberation
        // Mono — et en Courier New là où aucune n'existe. Aucune n'était embarquée.
        // Fira Mono est auto-hébergée (globals.css) ; la pile système reste derrière
        // comme repli le temps que la face se charge.
        mono: ['Fira Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      fontSize: {
        xs:   ['0.75rem',  { lineHeight: '1rem' }],
        sm:   ['0.875rem', { lineHeight: '1.25rem' }],
        base: ['1rem',     { lineHeight: '1.5rem' }],
        lg:   ['1.125rem', { lineHeight: '1.75rem' }],
        xl:   ['1.25rem',  { lineHeight: '1.75rem' }],
        '2xl':['1.5rem',   { lineHeight: '2rem' }],
      },
      transitionDuration: {
        DEFAULT: '150ms',  // ≤ 150ms — règle Design System
      },
      borderRadius: {
        DEFAULT: '8px',
        lg: '10px',
        xl: '16px',
      },
      // Élévation Mission Control : highlight interne haut (relief) + ombre
      // profonde diffuse ; les éléments accent portent un GLOW, jamais d'ombre dure.
      boxShadow: {
        'sf-soft': '0 2px 10px rgba(0, 0, 0, 0.15)',
        'sf-card': 'inset 0 1px 0 rgba(255, 255, 255, 0.05), 0 4px 20px rgba(0, 0, 0, 0.2)',
        'sf-card-hover': 'inset 0 1px 0 rgba(255, 255, 255, 0.07), 0 8px 32px rgba(0, 0, 0, 0.3)',
        'sf-accent': '0 0 15px rgb(var(--color-accent-rgb) / 0.30)',
        'sf-glow-success': '0 0 5px rgba(16, 185, 129, 0.5)',
        'sf-glow-warning': '0 0 5px rgba(245, 158, 11, 0.5)',
        'sf-glow-danger':  '0 0 5px rgba(239, 68, 68, 0.5)',
      },
    },
  },
  plugins: [],
}

export default config
