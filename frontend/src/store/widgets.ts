import { create } from 'zustand'

/**
 * État partagé des deux panneaux flottants (Assistant IA + Retour/Feedback).
 *
 * Les boutons déclencheurs vivent désormais dans la TOPBAR (décision Ed 21/07 :
 * les FAB en bas à droite masquaient parfois les boutons d'action des drawers).
 * Le déclencheur (topbar) et le panneau (overlay, monté dans DashboardShell) sont
 * dans des composants distincts → ils partagent leur état ici.
 */
interface WidgetPanelsState {
  assistantOpen: boolean
  feedbackOpen: boolean
  toggleAssistant: () => void
  toggleFeedback: () => void
  setAssistant: (v: boolean) => void
  setFeedback: (v: boolean) => void
}

export const useWidgetPanels = create<WidgetPanelsState>((set) => ({
  assistantOpen: false,
  feedbackOpen: false,
  // Ouvrir l'un ferme l'autre (deux gros overlays au même endroit).
  toggleAssistant: () => set((s) => ({ assistantOpen: !s.assistantOpen, feedbackOpen: false })),
  toggleFeedback: () => set((s) => ({ feedbackOpen: !s.feedbackOpen, assistantOpen: false })),
  setAssistant: (v) => set({ assistantOpen: v }),
  setFeedback: (v) => set({ feedbackOpen: v }),
}))
