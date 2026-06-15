const agentForm = document.getElementById("agentForm");
const voiceprintForm = document.getElementById("voiceprintForm");
const splitPdfForm = document.getElementById("splitPdfForm");
const videoForm = document.getElementById("videoForm");
const voiceprintSelect = document.getElementById("voiceprintSelect");
const agentStatus = document.getElementById("agentStatus");
const agentPptxLink = document.getElementById("agentPptxLink");
const agentScriptsLink = document.getElementById("agentScriptsLink");
const agentBundleLink = document.getElementById("agentBundleLink");
const stylePresetSelect = document.getElementById("stylePresetSelect");
const stylePresetDescription = document.getElementById("stylePresetDescription");
const legacyStyleInput = document.getElementById("legacyStyleInput");
const voiceprintStatus = document.getElementById("voiceprintStatus");
const splitStatus = document.getElementById("splitStatus");
const videoStatus = document.getElementById("videoStatus");
const videoLink = document.getElementById("videoLink");
const scriptsContract = document.getElementById("scriptsContract");
const visionContract = document.getElementById("visionContract");

scriptsContract.textContent = JSON.stringify({
  pages: [
    { image: "page_001.png", script: "第1页口播文案" },
    { image: "page_002.png", script: "第2页口播文案" }
  ]
}, null, 2);

visionContract.textContent = JSON.stringify({
  input: {
    page_index: 1,
    image_path: "/abs/path/page_001.png",
    image_format: "png",
    prompt: "根据这页PPT图片生成适合口播的中文讲解文本",
    constraints: ["中文", "适合口播", "不超过120字"]
  },
  output: {
    page_index: 1,
    prompt: "根据这页PPT图片生成适合口播的中文讲解文本",
    script: "第1页的口播文本待外部大模型生成。",
    raw_response: {
      provider: "placeholder",
      model: "vision-to-text",
      input: {
        page_index: 1,
        image_path: "/abs/path/page_001.png",
        image_format: "png",
        prompt: "根据这页PPT图片生成适合口播的中文讲解文本",
        constraints: ["中文", "适合口播", "不超过120字"]
      },
      output: { script: "..." }
    }
  }
}, null, 2);

function hideAgentLinks() {
  [agentPptxLink, agentScriptsLink, agentBundleLink].forEach(link => {
    link.hidden = true;
    link.href = "#";
  });
}

async function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function loadVoiceprints() {
  const res = await fetch("/api/voiceprints");
  const data = await res.json();
  voiceprintSelect.innerHTML = "";
  data.forEach(item => {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = `${item.name} (${item.source})`;
    voiceprintSelect.appendChild(option);
  });
}

async function loadStylePresets() {
  if (!stylePresetSelect) return;
  const res = await fetch("/api/style-presets");
  const data = await res.json();
  const presets = data.presets || [];
  stylePresetSelect.innerHTML = "";
  presets.forEach(preset => {
    const option = document.createElement("option");
    option.value = preset.id;
    option.textContent = preset.name;
    option.dataset.description = preset.description || "";
    option.dataset.stylePrompt = preset.style_prompt || preset.name;
    stylePresetSelect.appendChild(option);
  });
  syncStylePresetDescription();
}

function syncStylePresetDescription() {
  if (!stylePresetSelect) return;
  const option = stylePresetSelect.selectedOptions[0];
  if (!option) return;
  if (stylePresetDescription) {
    stylePresetDescription.textContent = `${option.textContent}：${option.dataset.description || "使用该预设生成 PPT 视觉风格。"}`;
  }
  if (legacyStyleInput) {
    legacyStyleInput.value = option.dataset.stylePrompt || option.textContent;
  }
}

async function pollVideoJob(jobId) {
  while (true) {
    const res = await fetch(`/api/video-jobs/${jobId}`);
    const data = await res.json();
    videoStatus.textContent = JSON.stringify(data, null, 2);
    if (data.status === "done") {
      videoLink.hidden = false;
      videoLink.href = `/api/video-jobs/${jobId}/video`;
      videoLink.textContent = "下载/打开视频";
      return;
    }
    if (data.status === "failed") {
      return;
    }
    await sleep(2000);
  }
}

async function pollAgentJob(jobId) {
  while (true) {
    const res = await fetch(`/api/agent-jobs/${jobId}`);
    const data = await res.json();
    agentStatus.textContent = JSON.stringify(data, null, 2);
    if (data.status === "done") {
      agentPptxLink.hidden = false;
      agentPptxLink.href = `/api/agent-jobs/${jobId}/pptx`;
      agentScriptsLink.hidden = false;
      agentScriptsLink.href = `/api/agent-jobs/${jobId}/scripts`;
      agentBundleLink.hidden = false;
      agentBundleLink.href = `/api/agent-jobs/${jobId}/bundle`;
      return;
    }
    if (data.status === "failed") {
      return;
    }
    await sleep(2000);
  }
}

agentForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  agentStatus.textContent = "提交中...";
  hideAgentLinks();
  syncStylePresetDescription();
  const fd = new FormData(agentForm);
  const res = await fetch("/api/agent-jobs", { method: "POST", body: fd });
  const data = await res.json();
  if (!res.ok) {
    agentStatus.textContent = JSON.stringify(data, null, 2);
    return;
  }
  await pollAgentJob(data.job_id);
});

if (stylePresetSelect) {
  stylePresetSelect.addEventListener("change", syncStylePresetDescription);
}

voiceprintForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  voiceprintStatus.textContent = "提交中...";
  const fd = new FormData(voiceprintForm);
  const res = await fetch("/api/voiceprints/extract", { method: "POST", body: fd });
  const data = await res.json();
  voiceprintStatus.textContent = JSON.stringify(data, null, 2);
  if (res.ok) {
    await loadVoiceprints();
  }
});

splitPdfForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  splitStatus.textContent = "处理中...";
  const fd = new FormData(splitPdfForm);
  const res = await fetch("/api/pdf/split", { method: "POST", body: fd });
  if (!res.ok) {
    splitStatus.textContent = JSON.stringify(await res.json(), null, 2);
    return;
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "images.zip";
  a.click();
  URL.revokeObjectURL(url);
  splitStatus.textContent = "已生成并开始下载图片 ZIP";
});

videoForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  videoStatus.textContent = "提交中...";
  videoLink.hidden = true;
  const fd = new FormData(videoForm);
  fd.append("voiceprint_id", voiceprintSelect.value);
  const res = await fetch("/api/video-jobs", { method: "POST", body: fd });
  const data = await res.json();
  if (!res.ok) {
    videoStatus.textContent = JSON.stringify(data, null, 2);
    return;
  }
  await pollVideoJob(data.job_id);
});

loadVoiceprints();
loadStylePresets();
