(function () {
  const vscode = acquireVsCodeApi();
  const statusEl = document.getElementById("status");
  const editorEl = document.getElementById("editor");

  let suppressNextInput = false;

  window.addEventListener("message", (event) => {
    const m = event.data;
    if (m?.type !== "state") return;
    statusEl.textContent = m.missing
      ? "No file — open a workspace or set sidebarNotes.globalFile"
      : m.filePath;

    // Only update textarea if text changed externally (avoid clobbering cursor position)
    if (editorEl.value !== m.text) {
      suppressNextInput = true;
      editorEl.value = m.text ?? "";
    }
  });

  editorEl.addEventListener("input", () => {
    if (suppressNextInput) {
      suppressNextInput = false;
      return;
    }
    vscode.postMessage({ type: "save", text: editorEl.value });
  });

  statusEl.addEventListener("click", () => {
    vscode.postMessage({ type: "openFile" });
  });

  vscode.postMessage({ type: "ready" });
})();
