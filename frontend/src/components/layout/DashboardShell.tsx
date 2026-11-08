import Sidebar from './Sidebar'
import AIAssistantWidget from '@/components/assistant/AIAssistantWidget'
import FeedbackWidget from '@/components/feedback/FeedbackWidget'
import DemoMode from './DemoMode'
import DemoTips from './DemoTips'
import ReadOnlyNudge from './ReadOnlyNudge'

interface DashboardShellProps {
  children: React.ReactNode
}

export default function DashboardShell({ children }: DashboardShellProps) {
  return (
    <div className="flex h-screen overflow-hidden bg-canvas relative">
      {/* Fond dot-grid (Mission Control) — sur TOUTES les pages, sous tout le contenu.
          Fondu haut/bas pour rester discret et ne pas gêner la lecture des tableaux. */}
      <div
        className="sf-dotted absolute inset-0 z-0 pointer-events-none opacity-[0.35]"
        style={{
          maskImage: 'linear-gradient(180deg, rgba(0,0,0,0.9), transparent 35%, transparent 65%, rgba(0,0,0,0.6))',
          WebkitMaskImage: 'linear-gradient(180deg, rgba(0,0,0,0.9), transparent 35%, transparent 65%, rgba(0,0,0,0.6))',
        }}
        aria-hidden="true"
      />
      {/* Aurora ambiante (Mission Control) — CSS pur, sous tout le contenu */}
      <div className="absolute inset-0 z-0 pointer-events-none opacity-40 overflow-hidden" aria-hidden="true">
        <div className="sf-aurora" />
      </div>
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden relative z-10">
        <DemoMode />
        {children}
      </div>
      {/* Compte démo : l'assistant IA s'affiche en VITRINE statique (aperçu sans appel LLM). */}
      <AIAssistantWidget />
      <FeedbackWidget />
      {/* Bulles d'infos contextuelles du mode démo (comptes is_demo uniquement) */}
      <DemoTips />
      {/* Nudge « lecture seule » : capte les interactions d'écriture dans les zones
          `data-write-perm` que l'utilisateur n'a pas le droit de modifier. */}
      <ReadOnlyNudge />
    </div>
  )
}
