(() => {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const form = byId("upload-form");
  const key = byId("access-key");
  const file = byId("pdf-file");
  const button = byId("upload-button");
  const result = byId("result");
  let busy = false;
  const timeoutMs = 180000;
  const unknownOutcome = "The outcome is unknown; processing may continue on the server. Nothing was automatically retried. Wait for processing to finish before deliberately submitting the identical PDF to retrieve its stored result.";

  function showError(message) {
    byId("error-message").textContent = message;
    byId("error-area").hidden = false;
  }

  function setBusy(value) {
    busy = value;
    button.disabled = value;
    key.disabled = value;
    file.disabled = value;
    form.setAttribute("aria-busy", String(value));
    byId("waiting").hidden = !value;
    button.textContent = value ? "Processing…" : "Upload PDF";
  }

  function textValue(value) {
    return value === null || value === undefined ? "Unknown" : String(value);
  }

  function renderReceipt(receipt) {
    const localLabels = {
      saved: ["Saved locally · validation passed", "success"],
      needs_review: ["Saved locally · needs review", "attention"],
      failed: ["Processing failed · no successful local save confirmed", "error"],
      processing: ["Processing · local save not yet confirmed", "attention"],
    };
    const syncLabels = {
      synced: ["Synced to Airtable", "success"],
      failed: ["Sync failed · not confirmed synchronized", "error"],
      unknown: ["Sync outcome unknown · reconciliation required", "attention"],
      pending: ["Sync pending · not confirmed synchronized", "attention"],
      not_configured: ["Airtable is not configured", "attention"],
      skipped: ["Sync skipped", "attention"],
    };
    for (const [id, state, labels] of [
      ["local-status", receipt.status, localLabels],
      ["sync-status", receipt.sync?.status, syncLabels],
    ]) {
      const [label, tone] = Object.hasOwn(labels, state) ? labels[state] : ["Unknown status", "attention"];
      byId(id).textContent = label;
      byId(id).dataset.tone = tone;
    }
    byId("receipt-id").textContent = `Receipt ID: ${textValue(receipt.receipt_id)}`;
    byId("record-id").hidden = !receipt.sync?.record_id;
    byId("record-id").textContent = receipt.sync?.record_id ? `Airtable record ID: ${receipt.sync.record_id}` : "";
    byId("sync-note").textContent = ["failed", "unknown", "pending"].includes(receipt.sync?.status)
      ? "The local record status above is separate from sync. No automatic retry or status polling is performed. An unknown sync outcome requires reconciliation before another creation attempt."
      : "";

    const details = byId("receipt-details");
    details.replaceChildren();
    const data = receipt.data;
    for (const [field, label] of [
      ["merchant", "Merchant"], ["date", "Date"], ["currency", "Currency"],
      ["total", "Total"], ["receipt_number", "Receipt number"], ["subtotal", "Subtotal"],
      ["discount", "Discount"], ["tax", "Tax"], ["tip", "Tip"],
    ]) {
      const group = document.createElement("div");
      const term = document.createElement("dt");
      const value = document.createElement("dd");
      term.textContent = label;
      value.textContent = textValue(data?.[field]);
      group.append(term, value);
      details.append(group);
    }

    const items = byId("items");
    items.replaceChildren();
    const lines = Array.isArray(data?.items) ? data.items : [];
    byId("items-wrapper").hidden = lines.length === 0;
    byId("items-empty").hidden = lines.length > 0;
    byId("items-empty").textContent = data?.items === null || !data ? "Line items are unknown." : "No line items returned.";
    for (const item of lines) {
      const row = document.createElement("tr");
      for (const field of ["description", "quantity", "unit_price", "amount"]) {
        const cell = document.createElement("td");
        cell.textContent = textValue(item?.[field]);
        row.append(cell);
      }
      items.append(row);
    }
    const issues = byId("validation-issues");
    issues.replaceChildren();
    byId("validation-status").textContent = receipt.status === "failed"
      ? "Processing failed; validation did not establish a successful result."
      : receipt.validation?.passed === true ? "Passed the applicable validation checks." : "Review required.";
    for (const issue of receipt.validation?.issues || []) {
      const row = document.createElement("li");
      row.textContent = `${textValue(issue.code)} · ${textValue(issue.field)}: ${textValue(issue.message)}`;
      issues.append(row);
    }
    result.hidden = false;
    result.focus();
  }

  function httpError(response, body) {
    const code = body?.detail?.code;
    if (response.status === 401) return "Access denied. Check your application access key and submit again.";
    const fileErrors = {
      empty_file: "The selected file is empty. Choose a non-empty PDF.",
      unsupported_media_type: "The file is not a supported PDF. Choose a PDF document.",
      invalid_pdf: "The PDF is unreadable or has no pages. Choose a valid PDF.",
      encrypted_pdf: "Encrypted PDFs are not supported. Choose an unencrypted PDF.",
      file_too_large: "The PDF exceeds the server's upload size limit.",
      too_many_pages: "The PDF exceeds the server's page limit.",
      request_too_large: "The upload request exceeds the server's size limit.",
    };
    if (fileErrors[code]) return fileErrors[code];
    if (response.status === 504 || body?.detail?.outcome === "unknown") return `HTTP ${response.status}. ${unknownOutcome}`;
    if ([400, 413, 415, 422].includes(response.status)) return `The server rejected the file or upload parameters (HTTP ${response.status}). Check the PDF before submitting again.`;
    return `The server could not complete this request (HTTP ${response.status}). ${unknownOutcome}`;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || !form.reportValidity()) return;
    byId("error-area").hidden = true;
    result.hidden = true;
    const payload = new FormData();
    payload.append("file", file.files[0]);
    const controller = new AbortController();
    setBusy(true);
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch("/api/v1/receipts", {
        method: "POST", headers: {"X-API-Key": key.value}, body: payload,
        signal: controller.signal, cache: "no-store", redirect: "error", credentials: "omit",
      });
      let body;
      try {
        body = await response.json();
      } catch (error) {
        if (controller.signal.aborted) throw error;
        showError(response.ok ? `The server returned an unreadable response. ${unknownOutcome}` : httpError(response, null));
        return;
      }
      if ((response.ok || response.status === 502) && typeof body?.receipt_id === "string"
          && body.receipt_id && body.sync && body.validation && typeof body.status === "string") {
        renderReceipt(body);
        if (!response.ok || body.status === "failed") showError("Receipt processing failed. The returned receipt ID identifies the stored failure; no successful processing is claimed.");
      } else {
        showError(response.ok ? `The server returned an unexpected response. ${unknownOutcome}` : httpError(response, body));
      }
    } catch (error) {
      showError(controller.signal.aborted ? `Browser request timed out. ${unknownOutcome}` : `The connection failed or was interrupted. ${unknownOutcome}`);
    } finally {
      window.clearTimeout(timer);
      setBusy(false);
    }
  });

  window.addEventListener("pagehide", () => { key.value = ""; });
  window.addEventListener("pageshow", (event) => { if (event.persisted) key.value = ""; });
})();
