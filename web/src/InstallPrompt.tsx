import { useEffect, useState } from 'react';
import { Share, X } from 'lucide-react';

function isIosDevice() {
  return /iPad|iPhone|iPod/.test(navigator.userAgent);
}

function isStandalone() {
  return (
    window.matchMedia('(display-mode: standalone)').matches ||
    ('standalone' in navigator && (navigator as Navigator & { standalone?: boolean }).standalone === true)
  );
}

export default function InstallPrompt() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (!isIosDevice() || isStandalone()) return;
    if (localStorage.getItem('marineagent-install-dismissed') === '1') return;
    setVisible(true);
  }, []);

  if (!visible) return null;

  return (
    <div className="install-prompt" role="status">
      <div className="install-prompt-content">
        <Share size={18} />
        <span>
          Install MarineAgent: tap <strong>Share</strong> then <strong>Add to Home Screen</strong>
        </span>
      </div>
      <button
        type="button"
        className="install-prompt-close"
        aria-label="Dismiss install instructions"
        onClick={() => {
          localStorage.setItem('marineagent-install-dismissed', '1');
          setVisible(false);
        }}
      >
        <X size={18} />
      </button>
    </div>
  );
}