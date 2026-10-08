import { useEffect } from 'react'

/**
 * Chiama ``spegni`` quando un trascinamento finisce, dovunque finisca.
 *
 * Ogni zona che si accende sotto un file trascinato si spegneva solo se il
 * file veniva lasciato *su di lei*: lasciandolo altrove (la chat, che lo
 * trattiene per allegarlo) il tratteggio restava acceso. Il rilascio si
 * ascolta sulla finestra in fase di cattura, cosi' arriva anche quando
 * qualcuno ferma la propagazione.
 */
export function useFineTrascinamento(spegni) {
  useEffect(() => {
    const fine = () => spegni()
    const fuori = (e) => { if (!e.relatedTarget) spegni() }   // uscito dalla finestra
    window.addEventListener('drop', fine, true)
    window.addEventListener('dragend', fine, true)
    window.addEventListener('dragleave', fuori, true)
    return () => {
      window.removeEventListener('drop', fine, true)
      window.removeEventListener('dragend', fine, true)
      window.removeEventListener('dragleave', fuori, true)
    }
  }, [spegni])
}
