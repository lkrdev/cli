"""Build single-file Looker Code Mode WASM bundle (dist/codemode.js)."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
CRATE_DIR = ROOT_DIR / "lkr" / "codemode" / "wasm"
MANIFEST_PATH = CRATE_DIR / "Cargo.toml"
TARGET_DIR = CRATE_DIR / "target"
WASM_BINARY = TARGET_DIR / "wasm32-unknown-unknown" / "release" / "lkr_codemode_wasm.wasm"
BINDGEN_DIR = TARGET_DIR / "bindgen"
DIST_DIR = ROOT_DIR / "dist"
OUTPUT_JS = DIST_DIR / "codemode.js"


def build_wasm() -> Path:
    env = os.environ.copy()
    cargo_bin = Path.home() / ".cargo" / "bin"
    if cargo_bin.exists():
        env["PATH"] = f"{cargo_bin}:{env.get('PATH', '')}"

    rustflags = env.get("RUSTFLAGS", "")
    if 'getrandom_backend="wasm_js"' not in rustflags:
        env["RUSTFLAGS"] = f'{rustflags} --cfg getrandom_backend="wasm_js"'.strip()

    subprocess.run(
        [
            "cargo",
            "build",
            "--release",
            "--target",
            "wasm32-unknown-unknown",
            "--manifest-path",
            str(MANIFEST_PATH),
        ],
        env=env,
        check=True,
    )

    if BINDGEN_DIR.exists():
        shutil.rmtree(BINDGEN_DIR)
    BINDGEN_DIR.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [
            "wasm-bindgen",
            "--target",
            "no-modules",
            "--no-typescript",
            "--out-dir",
            str(BINDGEN_DIR),
            str(WASM_BINARY),
        ],
        env=env,
        check=True,
    )

    glue_js = (BINDGEN_DIR / "lkr_codemode_wasm.js").read_text(encoding="utf-8")
    wasm_bytes = (BINDGEN_DIR / "lkr_codemode_wasm_bg.wasm").read_bytes()
    wasm_b64 = base64.b64encode(wasm_bytes).decode("ascii")

    DIST_DIR.mkdir(parents=True, exist_ok=True)

    bundle = f"""/*!
 * Looker Code Mode WASM Sandbox (lkr-dev-cli)
 * Self-contained Monty Python sandbox + Looker Extension Host (@looker/chatty) bridge.
 */
(function (root) {{
  "use strict";

{glue_js}

  const bin = atob("{wasm_b64}");
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  try {{ wasm_bindgen.initSync({{ module: bytes }}); }} catch (_) {{}}
  function initAsync() {{
    return wasm_bindgen({{ module_or_path: bytes }}).then(function () {{
      return wasm_bindgen;
    }});
  }}

  function isExtSdk(x) {{
    return Boolean(x && (typeof x.invokeCoreSdkRaw === "function" || typeof x.invokeCoreSdk === "function"));
  }}

  function resolveExtSdk(opts) {{
    const core = opts && (opts.sdk || opts.core40SDK);
    const tr = core && core.authSession && core.authSession.transport;
    return (
      (isExtSdk(opts) && opts) ||
      (opts && (opts.extensionSDK || opts.extensionSdk)) ||
      (tr && (tr.extensionHost || (tr.hostConnection && tr.hostConnection.hostConnection))) ||
      root.__LKR_EXTENSION_SDK__ ||
      root.extensionSDK ||
      root.lookerExtensionSDK ||
      null
    );
  }}

  function syncHost(wb, opts, extSdk) {{
    const orig = opts && (opts.targetOrigin || opts.hostOrigin || opts.hostUrl);
    const hd = extSdk && extSdk.lookerHostData;
    wb.setHostData(hd || null, orig ? String(orig) : undefined);
  }}

  function normalizeRunArgs(codeOrParams, options) {{
    let code = codeOrParams;
    let opts = options || {{}};
    if (codeOrParams && typeof codeOrParams === "object") {{
      code = codeOrParams.code || "";
      opts = codeOrParams;
    }} else if (isExtSdk(opts)) {{
      opts = {{ extensionSDK: opts }};
    }}
    const extSdk = resolveExtSdk(opts);
    const core = opts.sdk || opts.core40SDK;
    const transport = core && core.authSession && core.authSession.transport;
    let handler = typeof opts.requestHandler === "function" ? opts.requestHandler : undefined;
    if (!handler && extSdk) {{
      if (typeof extSdk.invokeCoreSdkRaw === "function") {{
        handler = function (m, p, q, b) {{
          return extSdk.invokeCoreSdkRaw(m, p, q, b, "4.0");
        }};
      }} else if (typeof extSdk.invokeCoreSdk === "function") {{
        handler = function (m, p, q, b, o) {{
          return extSdk.invokeCoreSdk(m, p, q, b, undefined, o, "4.0");
        }};
      }}
    }} else if (!handler && transport && typeof transport.rawRequest === "function") {{
      handler = function (m, p, q, b) {{
        return transport.rawRequest(String(m || "GET").toUpperCase(), p, q, b);
      }};
    }}
    return {{
      code: String(code || ""),
      varsJson: opts.vars ? JSON.stringify(opts.vars) : undefined,
      allowUpdate: Boolean(opts.allowUpdateSession || opts.allow_update_session),
      handler: handler,
      opts: opts,
      extSdk: extSdk
    }};
  }}

  function getToolDefinition(name) {{
    return {{
      type: "function",
      name: name || "run_looker_codemode",
      description:
        'Execute Python code in the browser Looker Code Mode WASM (Monty) sandbox with direct access to all Looker 4.0 SDK methods (e.g. `lookml_model_explore(target_model, target_explore)`, `run_inline_query("json", {{...}})`, `me()`, `search_dashboards()`, `help("*query*")`, `lookup("run_inline_query")`, `lookup_type("WriteQuery")`). Variables passed in `vars` (such as `target_model`, `target_explore`, and `target_folder_id`) are pre-injected. Return a compact dict/list instead of raw multi-MB responses.',
      parameters: {{
        type: "object",
        properties: {{
          code: {{
            type: "string",
            description:
              "Python snippet to execute in Monty sandbox. Use `return ...` to return the result (dicts/lists/strings). All Looker 4.0 SDK methods are available globally or on `sdk.<method>(...)`."
          }}
        }},
        required: ["code"]
      }}
    }};
  }}

  function runCode(codeOrParams, options) {{
    const n = normalizeRunArgs(codeOrParams, options);
    return initAsync().then(function (wb) {{
      syncHost(wb, n.opts, n.extSdk);
      return wb.runPythonCodeRaw(n.code, n.varsJson, n.allowUpdate, n.handler);
    }});
  }}

  const LkrCodeMode = Object.assign({{}}, wasm_bindgen, {{
    init: function () {{
      return initAsync().then(function () {{ return LkrCodeMode; }});
    }},
    getCodeModeRuntime: function () {{ return LkrCodeMode; }},
    getToolDefinition: getToolDefinition,
    RUN_LOOKER_CODEMODE_TOOL: getToolDefinition("run_looker_codemode"),
    connect: function (options) {{
      const n = normalizeRunArgs("", options);
      return initAsync().then(function (wb) {{
        syncHost(wb, n.opts, n.extSdk);
        return n.extSdk ? wb.getHostData() : wb.connectHost();
      }});
    }},
    setExtensionSDK: function (sdk) {{
      root.__LKR_EXTENSION_SDK__ = sdk;
      return initAsync().then(function (wb) {{
        syncHost(wb, null, sdk);
      }});
    }},
    getHostData: function () {{
      syncHost(wasm_bindgen, null, resolveExtSdk(null));
      return wasm_bindgen.getHostData();
    }},
    runPythonCode: runCode,
    run_python_code: runCode,
    executeLookerCodeMode: runCode
  }});

  root.LkrCodeMode = LkrCodeMode;
  root.lkrCodeMode = LkrCodeMode;
  if (typeof module !== "undefined" && module.exports) {{
    module.exports = LkrCodeMode;
  }}
}})(typeof globalThis !== "undefined" ? globalThis : typeof window !== "undefined" ? window : this);
"""

    OUTPUT_JS.write_text(bundle, encoding="utf-8")
    size_kb = OUTPUT_JS.stat().st_size / 1024.0
    print(f"Built {OUTPUT_JS} ({size_kb:.1f} KB)")
    return OUTPUT_JS


if __name__ == "__main__":
    try:
        build_wasm()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
