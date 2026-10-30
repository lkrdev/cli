import { connectExtensionHost, ExtensionSDK } from "@looker/extension-sdk";
import React, { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "../../../dist/codemode.js";

export interface LkrCodeModeAPI {
  setExtensionSDK: (sdk: ExtensionSDK) => Promise<void>;
  runPythonCode: (
    code: string,
    options?: { extensionSDK?: ExtensionSDK },
  ) => Promise<string>;
}

declare global {
  interface Window {
    LkrCodeMode?: LkrCodeModeAPI;
  }
}

const DEFAULT_CODE = `return me()`;

const SNIPPETS: { label: string; code: string }[] = [
  { label: "Current User (me)", code: "return me()" },
  { label: "Search Dashboard Methods", code: 'return help("*dashboard*")' },
  { label: "Inspect WriteQuery Type", code: 'return lookup_type("WriteQuery")' },
  {
    label: "List Dashboards (id, title)",
    code: 'return all_dashboards(fields="id,title")[:10]',
  },
  {
    label: "Looker Extension Host Info",
    code: "return host_data()",
  },
];

export const CodeModePlayground: React.FC<{ host?: ExtensionSDK }> = ({
  host,
}) => {
  const [extensionSDK, setExtensionSDK] = useState<ExtensionSDK | undefined>(
    host,
  );
  const [hostUrl, setHostUrl] = useState<string>("");
  const [code, setCode] = useState<string>(DEFAULT_CODE);
  const [output, setOutput] = useState<string>("Connecting to Looker host...");
  const [running, setRunning] = useState<boolean>(false);
  const [durationMs, setDurationMs] = useState<number | null>(null);

  const runCode = useCallback(
    async (sourceCode: string, sdkInstance?: ExtensionSDK) => {
      const api = window.LkrCodeMode;
      if (!api) {
        setOutput("Error: window.LkrCodeMode is not loaded.");
        return;
      }
      setRunning(true);
      const t0 = performance.now();
      try {
        const res = await api.runPythonCode(sourceCode, {
          extensionSDK: sdkInstance ?? extensionSDK,
        });
        setDurationMs(Math.round(performance.now() - t0));
        setOutput(res || "(None)");
      } catch (err: unknown) {
        setDurationMs(Math.round(performance.now() - t0));
        setOutput(
          `Error: ${err instanceof Error ? err.message : String(err)}`,
        );
      } finally {
        setRunning(false);
      }
    },
    [extensionSDK],
  );

  useEffect(() => {
    let cancelled = false;
    async function initHost() {
      try {
        const sdk = host ?? (await connectExtensionHost());
        if (cancelled) return;
        setExtensionSDK(sdk);
        const parentUrl =
          sdk.lookerHostData?.hostUrl ||
          (sdk.lookerHostData as Record<string, unknown> | undefined)
            ?.hostOrigin ||
          "";
        setHostUrl(String(parentUrl || "connected"));
        if (window.LkrCodeMode) {
          await window.LkrCodeMode.setExtensionSDK(sdk);
        }
        await runCode(DEFAULT_CODE, sdk);
      } catch {
        if (cancelled) return;
        setHostUrl("offline / sandbox");
        await runCode(DEFAULT_CODE);
      }
    }
    initHost();
    return () => {
      cancelled = true;
    };
  }, [host]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      runCode(code);
      return;
    }
    if (e.key === "Tab") {
      e.preventDefault();
      const target = e.currentTarget;
      const start = target.selectionStart;
      const end = target.selectionEnd;
      const next = code.substring(0, start) + "    " + code.substring(end);
      setCode(next);
      requestAnimationFrame(() => {
        target.selectionStart = target.selectionEnd = start + 4;
      });
    }
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        width: "100vw",
        fontFamily:
          'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        backgroundColor: "#0f172a",
        color: "#f8fafc",
        boxSizing: "border-box",
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "10px 16px",
          borderBottom: "1px solid #1e293b",
          backgroundColor: "#020617",
          gap: "12px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <strong style={{ fontSize: "14px", letterSpacing: "0.02em" }}>
            lkr code-mode
          </strong>
          <span
            style={{
              fontSize: "11px",
              padding: "2px 8px",
              borderRadius: "9999px",
              backgroundColor: "#1e293b",
              color: "#94a3b8",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
            }}
          >
            monty wasm
          </span>
          {hostUrl && (
            <span
              style={{
                fontSize: "11px",
                color: "#64748b",
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
              }}
            >
              {hostUrl}
            </span>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <select
            aria-label="Code snippet"
            value=""
            onChange={(e) => {
              const selected = e.target.value;
              if (selected) {
                setCode(selected);
                runCode(selected);
              }
            }}
            style={{
              backgroundColor: "#1e293b",
              color: "#e2e8f0",
              border: "1px solid #334155",
              borderRadius: "6px",
              padding: "6px 10px",
              fontSize: "12px",
              cursor: "pointer",
            }}
          >
            <option value="" disabled>
              Examples...
            </option>
            {SNIPPETS.map((s) => (
              <option key={s.label} value={s.code}>
                {s.label}
              </option>
            ))}
          </select>

          <button
            type="button"
            onClick={() => runCode(code)}
            disabled={running}
            style={{
              backgroundColor: running ? "#334155" : "#2563eb",
              color: "#ffffff",
              border: "none",
              borderRadius: "6px",
              padding: "6px 14px",
              fontSize: "12px",
              fontWeight: 600,
              cursor: running ? "wait" : "pointer",
            }}
          >
            {running ? "Running..." : "Run (⌘/Ctrl+Enter)"}
          </button>
        </div>
      </header>

      <main
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          flex: 1,
          minHeight: 0,
        }}
      >
        <section
          style={{
            display: "flex",
            flexDirection: "column",
            borderRight: "1px solid #1e293b",
            minHeight: 0,
          }}
        >
          <div
            style={{
              padding: "6px 12px",
              fontSize: "11px",
              color: "#94a3b8",
              borderBottom: "1px solid #1e293b",
              backgroundColor: "#090d16",
            }}
          >
            main.py
          </div>
          <textarea
            value={code}
            onChange={(e) => setCode(e.target.value)}
            onKeyDown={handleKeyDown}
            spellCheck={false}
            style={{
              flex: 1,
              width: "100%",
              resize: "none",
              border: "none",
              outline: "none",
              padding: "14px",
              backgroundColor: "#0f172a",
              color: "#f8fafc",
              fontFamily:
                'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Courier New", monospace',
              fontSize: "13px",
              lineHeight: 1.5,
              boxSizing: "border-box",
            }}
          />
        </section>

        <section
          style={{
            display: "flex",
            flexDirection: "column",
            minHeight: 0,
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              padding: "6px 12px",
              fontSize: "11px",
              color: "#94a3b8",
              borderBottom: "1px solid #1e293b",
              backgroundColor: "#090d16",
            }}
          >
            <span>Output</span>
            {durationMs !== null && <span>{durationMs} ms</span>}
          </div>
          <pre
            style={{
              flex: 1,
              margin: 0,
              padding: "14px",
              overflow: "auto",
              backgroundColor: "#090d16",
              color: output.startsWith("Error:") ? "#f87171" : "#e2e8f0",
              fontFamily:
                'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Courier New", monospace',
              fontSize: "12.5px",
              lineHeight: 1.5,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {output}
          </pre>
        </section>
      </main>
    </div>
  );
};

const mount = () => {
  const root = document.body.appendChild(document.createElement("div"));
  document.body.style.margin = "0";
  document.body.style.height = root.style.height = "100%";
  createRoot(root).render(<CodeModePlayground />);
};

if (typeof window !== "undefined") {
  if (document.readyState === "loading") {
    window.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }
}
