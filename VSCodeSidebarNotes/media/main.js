(function () {
  const vscode = acquireVsCodeApi();
  const statusEl = document.getElementById("status");
  const previewEl = document.getElementById("preview");
  const editorEl = document.getElementById("editor");

  let currentMode = "preview";
  let suppressNextInput = false;

  window.addEventListener("message", (event) => {
    const m = event.data;
    if (m?.type !== "state") return;
    currentMode = m.mode;
    statusEl.textContent = m.missing
      ? "No file — open a workspace or set sidebarNotes.globalFile"
      : m.filePath;

    if (m.mode === "preview") {
      previewEl.innerHTML = m.rendered ?? "";
      previewEl.classList.remove("hidden");
      editorEl.classList.add("hidden");
    } else {
      // Avoid the input handler firing for our programmatic value set
      suppressNextInput = true;
      editorEl.value = m.text ?? "";
      editorEl.classList.remove("hidden");
      previewEl.classList.add("hidden");
      editorEl.focus();
    }
  });

  editorEl.addEventListener("input", () => {
    if (suppressNextInput) {
      suppressNextInput = false;
      return;
    }
    vscode.postMessage({ type: "save", text: editorEl.value });
  });

  // Click-to-edit on preview
  previewEl.addEventListener("dblclick", () => {
    vscode.postMessage({ type: "toggleEdit" });
  });

  // Status bar text click opens the file
  statusEl.addEventListener("click", () => {
    vscode.postMessage({ type: "openFile" });
  });

  vscode.postMessage({ type: "ready" });
})();
