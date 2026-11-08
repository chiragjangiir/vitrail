'use client'

import { useEffect, useRef, useState } from 'react'

/**
 * Texte qui DÉFILE horizontalement (ping-pong) uniquement s'il déborde de son conteneur ;
 * sinon statique. Le conteneur doit avoir une largeur bornée (flex-1/min-w-0 ou largeur fixe).
 * Fallback accessibilité : `title` = texte complet.
 */
export default function MarqueeText({ text, className = '' }: { text: string; className?: string }) {
  const boxRef = useRef<HTMLDivElement>(null)
  const spanRef = useRef<HTMLSpanElement>(null)
  const [dx, setDx] = useState(0)

  useEffect(() => {
    const box = boxRef.current
    const span = spanRef.current
    if (!box || !span) return
    const measure = () => {
      const over = span.scrollWidth - box.clientWidth
      setDx(over > 2 ? over : 0)
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(box)
    return () => ro.disconnect()
  }, [text])

  return (
    <div ref={boxRef} className={`overflow-hidden whitespace-nowrap ${className}`} title={text}>
      <span
        ref={spanRef}
        className={`inline-block ${dx > 0 ? 'sf-marquee' : ''}`}
        style={
          dx > 0
            ? ({
                '--sf-marquee-x': `-${dx}px`,
                '--sf-marquee-dur': `${Math.max(5, Math.round(dx / 25))}s`,
              } as React.CSSProperties)
            : undefined
        }
      >
        {text}
      </span>
    </div>
  )
}
