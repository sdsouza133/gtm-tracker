import { useEffect, useRef, useState } from "react";

/** The little of Google Identity Services this page uses. */
type GoogleId = {
  initialize: (options: { client_id: string; callback: (response: { credential: string }) => void }) => void;
  renderButton: (parent: HTMLElement, options: Record<string, string | number>) => void;
};

declare global {
  interface Window {
    google?: { accounts: { id: GoogleId } };
  }
}

const SCRIPT = "https://accounts.google.com/gsi/client";
let loading: Promise<GoogleId> | null = null;

/** Loads Google's script once, however many times the sign-in page opens. */
function loadGoogle(): Promise<GoogleId> {
  const ready = window.google?.accounts.id;
  if (ready) return Promise.resolve(ready);
  loading ??= new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = SCRIPT;
    script.async = true;
    script.onload = () => {
      const id = window.google?.accounts.id;
      if (id) resolve(id);
      else reject(new Error("Google sign-in didn't start"));
    };
    script.onerror = () => {
      loading = null; // a later visit tries again
      script.remove();
      reject(new Error("Google sign-in didn't load"));
    };
    document.head.append(script);
  });
  return loading;
}

/** Google's own "Sign in with Google" button. It hands back an ID token for the server to check. */
export function GoogleButton({
  clientId,
  onCredential,
}: {
  clientId: string;
  onCredential: (credential: string) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const latest = useRef(onCredential);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    latest.current = onCredential;
  }, [onCredential]);

  useEffect(() => {
    let live = true;
    loadGoogle()
      .then((id) => {
        if (!live || !box.current) return;
        id.initialize({ client_id: clientId, callback: (response) => latest.current(response.credential) });
        id.renderButton(box.current, { theme: "outline", size: "large", text: "signin_with", width: 320 });
      })
      .catch(() => {
        if (live) setFailed(true);
      });
    return () => {
      live = false;
    };
  }, [clientId]);

  return (
    <>
      <div ref={box} data-testid="google-button" className="flex min-h-[44px] justify-center" />
      {failed && (
        <p role="alert" className="mt-3 text-sm font-medium text-bad">
          Couldn't load Google sign-in. Check your connection (or any blocker for accounts.google.com) and reload.
        </p>
      )}
    </>
  );
}
