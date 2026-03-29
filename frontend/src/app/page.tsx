"use client";

import { useState, useEffect, useRef, useCallback } from "react";

/* ─── Types ─── */

interface JobStep {
  [key: string]: string;
}

interface SeoData {
  long_form?: {
    title?: string;
    description?: string;
    tags?: string[];
    title_variants?: string[];
  };
  shorts?: {
    title?: string;
    description?: string;
    tags?: string[];
  }[];
}

interface JobResult {
  video_path?: string;
  short_paths?: string[];
  short_designs?: any[];
  seo_data?: SeoData;
  thumbnail_paths?: string[];
  thumbnail_data?: { long_form: string[]; shorts: string[][] };
  short_thumbnail_paths?: (string | null)[];
  community_posts?: { text: string; type: string; frame_image?: string; ai_image?: string }[];
  qa_scores?: {
    passed?: boolean;
    coherence_score?: number;
    engagement_prediction?: number;
    seo_score?: number;
    total_score?: number;
    issues?: string[];
    suggestions?: string[];
    short_scores?: {
      index: number;
      coherence: number;
      engagement: number;
      seo: number;
    }[];
  };
  filler_count?: number;
  dead_air_removed?: number;
  tangents_removed?: number;
  word_count?: number;
  original_duration?: number;
  edited_duration?: number;
  title_variants?: string[];
  intake_result?: any;
  edit_plan?: any;
}

interface Job {
  id: string;
  source: string;
  source_type: string;
  status: string;
  created_at: string;
  steps: JobStep;
  result?: JobResult;
  error?: string;
  youtube_video_id?: string;
  youtube_short_ids?: string[];
}

interface AuthStatus {
  youtube: boolean;
}

interface AssetStatus {
  intro: boolean;
  outro: boolean;
}

/* ─── Constants ─── */

const API = "/api";

const stepLabels: Record<string, string> = {
  heygen_generate: "Avatar generated",
  compose_ugc: "Video composed",
  download: "Downloaded",
  transcribe: "Transcribed",
  analyze: "Video analyzed",
  intake: "Content analyzed",
  edit_plan: "Edit planned",
  execute_edits: "Video edited",
  caption_longform: "Captions burned",
  short_design: "Shorts designed",
  short_creation: "Shorts created",
  packaging: "Packaged",
  thumbnail_gen: "Thumbnails ready",
  community_images: "Post images ready",
  qa_review: "QA complete",
  auto_publish: "Published to YouTube",
  community_posts: "Community posted",
};

const statusColor = (s: string) =>
  s === "complete"
    ? "text-green-400"
    : s === "running"
    ? "text-yellow-400"
    : "text-gray-600";

/* ─── Helpers ─── */

function fmtDuration(secs?: number): string {
  if (secs === undefined || secs === null) return "?";
  const m = Math.floor(secs / 60);
  const s = Math.round(secs % 60);
  return `${m}m${s > 0 ? ` ${s}s` : ""}`;
}

function scoreColor(val: number, max: number = 10): string {
  const ratio = val / max;
  if (ratio >= 0.7) return "bg-green-500";
  if (ratio >= 0.5) return "bg-yellow-500";
  return "bg-red-500";
}

function scoreTextColor(val: number, max: number = 10): string {
  const ratio = val / max;
  if (ratio >= 0.7) return "text-green-400";
  if (ratio >= 0.5) return "text-yellow-400";
  return "text-red-400";
}

function hookBadge(strength: number): { text: string; cls: string } {
  if (strength >= 8) return { text: `Hook: ${strength}/10`, cls: "bg-green-900 text-green-300" };
  if (strength >= 5) return { text: `Hook: ${strength}/10`, cls: "bg-yellow-900 text-yellow-300" };
  return { text: `Hook: ${strength}/10`, cls: "bg-red-900 text-red-300" };
}

function typeBadgeColor(type: string): string {
  switch (type) {
    case "teaser":
      return "bg-purple-900 text-purple-300";
    case "question":
      return "bg-blue-900 text-blue-300";
    case "bold_claim":
      return "bg-orange-900 text-orange-300";
    default:
      return "bg-gray-700 text-gray-300";
  }
}

/* ─── Tabs ─── */

type ReviewTab = "longform" | "shorts" | "community" | "qa";

const TAB_LABELS: { key: ReviewTab; label: string }[] = [
  { key: "longform", label: "Long-Form Video" },
  { key: "shorts", label: "Shorts" },
  { key: "community", label: "Community Posts" },
  { key: "qa", label: "QA Report" },
];

/* ─── Progress Bar Component ─── */

function ProgressBar({
  value,
  max,
  label,
}: {
  value: number;
  max: number;
  label: string;
}) {
  const pct = Math.min(100, Math.round((value / max) * 100));
  const color = scoreColor(value, max);
  const txtColor = scoreTextColor(value, max);
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-sm">
        <span className="text-gray-400">{label}</span>
        <span className={`font-bold ${txtColor}`}>
          {value}/{max}
        </span>
      </div>
      <div className="w-full bg-gray-700 rounded-full h-2.5">
        <div
          className={`${color} h-2.5 rounded-full transition-all`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

/* ─── Main Component ─── */

export default function Home() {
  const [videoUrl, setVideoUrl] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [authStatus, setAuthStatus] = useState<AuthStatus>({ youtube: false });
  const [assetStatus, setAssetStatus] = useState<AssetStatus | null>(null);
  const [selectedThumbs, setSelectedThumbs] = useState<Record<string, number>>(
    {}
  );
  const [selectedTitles, setSelectedTitles] = useState<Record<string, number>>(
    {}
  );
  const [publishTimes, setPublishTimes] = useState<Record<string, string>>({});
  const [dragActive, setDragActive] = useState(false);
  const [approving, setApproving] = useState<Record<string, string>>({});
  const [approveErrors, setApproveErrors] = useState<Record<string, string>>(
    {}
  );
  const [activeTab, setActiveTab] = useState<Record<string, ReviewTab>>({});
  const [copiedIdx, setCopiedIdx] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // V8: Avatar + UGC generation state
  type InputMode = "url" | "avatar" | "ugc";
  const [inputMode, setInputMode] = useState<InputMode>("url");
  const [avatarScript, setAvatarScript] = useState("");
  const [avatarId, setAvatarId] = useState("");
  const [ugcBrief, setUgcBrief] = useState("");
  const [ugcStyle, setUgcStyle] = useState("testimonial");
  const [ugcPersona, setUgcPersona] = useState("young professional");
  const [ugcDuration, setUgcDuration] = useState(30);
  const [ugcVoiceGender, setUgcVoiceGender] = useState("female");
  const [descriptionTemplate, setDescriptionTemplate] = useState("");
  const [customDescription, setCustomDescription] = useState("");
  const [videoInstructions, setVideoInstructions] = useState("");
  const [savedTemplates, setSavedTemplates] = useState<{id: string; name: string; content: string}[]>([]);
  const [newTemplateName, setNewTemplateName] = useState("");

  /* ─── API calls ─── */

  const fetchJobs = useCallback(async () => {
    try {
      const res = await fetch(`${API}/jobs`);
      const data = await res.json();
      setJobs((data.jobs || []).reverse());
    } catch (err) {
      console.warn("Failed to fetch jobs:", err);
    }
  }, []);

  const fetchAuth = useCallback(async () => {
    try {
      const res = await fetch(`/auth/status`);
      setAuthStatus(await res.json());
    } catch (err) {
      console.warn("Failed to fetch auth status:", err);
    }
  }, []);

  const fetchAssets = useCallback(async () => {
    try {
      const res = await fetch(`${API}/assets/status`);
      if (res.ok) {
        setAssetStatus(await res.json());
      }
    } catch (err) {
      console.warn("Failed to fetch asset status:", err);
    }
  }, []);

  const fetchTemplates = useCallback(async () => {
    try {
      const res = await fetch(`${API}/templates`);
      if (res.ok) {
        const data = await res.json();
        setSavedTemplates(data.templates || []);
      }
    } catch (err) {
      console.warn("Failed to fetch templates:", err);
    }
  }, []);

  useEffect(() => {
    fetchJobs();
    fetchAuth();
    fetchAssets();
    fetchTemplates();
    const interval = setInterval(fetchJobs, 3000);
    return () => clearInterval(interval);
  }, [fetchJobs, fetchAuth, fetchAssets, fetchTemplates]);

  /* ─── Handlers ─── */

  const handleAvatarSubmit = async () => {
    if (!avatarScript.trim()) return;
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API}/generate/avatar`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          script: avatarScript,
          avatar_id: avatarId,
        }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Failed to submit avatar generation");
      }
      setAvatarScript("");
      await fetchJobs();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  const handleUgcSubmit = async () => {
    if (!ugcBrief.trim()) return;
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API}/generate/ugc`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          brief: ugcBrief,
          style: ugcStyle,
          persona: ugcPersona,
          duration: ugcDuration,
          voice_gender: ugcVoiceGender,
        }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Failed to submit UGC generation");
      }
      setUgcBrief("");
      await fetchJobs();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  const handleUrlSubmit = async () => {
    if (!videoUrl.trim()) return;
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API}/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_url: videoUrl, description_template: descriptionTemplate, custom_description: customDescription, instructions: videoInstructions }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Failed to submit");
      }
      setVideoUrl("");
      await fetchJobs();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (file: File) => {
    setUploading(true);
    setError("");
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch(`${API}/upload`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Upload failed");
      }
      await fetchJobs();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFileUpload(file);
  };

  const handleApprove = async (jobId: string) => {
    if (approving[jobId]) return;
    setApproveErrors((prev) => ({ ...prev, [jobId]: "" }));
    setApproving((prev) => ({ ...prev, [jobId]: "Uploading long-form..." }));
    try {
      const shortsCount =
        jobs.find((j) => j.id === jobId)?.result?.short_paths?.length || 0;

      const progressSteps: string[] = [];
      for (let i = 1; i <= shortsCount; i++) {
        progressSteps.push(`Uploading Short ${i}...`);
      }

      let stepIndex = 0;
      const progressInterval = setInterval(() => {
        if (stepIndex < progressSteps.length) {
          setApproving((prev) => ({
            ...prev,
            [jobId]: progressSteps[stepIndex],
          }));
          stepIndex++;
        }
      }, 3000);

      const res = await fetch(`${API}/jobs/${jobId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          publish_at: publishTimes[jobId] || "",
          selected_thumbnail: selectedThumbs[jobId] || 0,
          selected_title_index: selectedTitles[jobId] || 0,
        }),
      });

      clearInterval(progressInterval);

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Approval failed");
      }
      setApproving((prev) => ({ ...prev, [jobId]: "done" }));
      await fetchJobs();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Approval failed";
      setApproveErrors((prev) => ({ ...prev, [jobId]: msg }));
      setApproving((prev) => {
        const next = { ...prev };
        delete next[jobId];
        return next;
      });
    }
  };

  const handleCopy = (text: string, key: string) => {
    navigator.clipboard.writeText(text);
    setCopiedIdx(key);
    setTimeout(() => setCopiedIdx(null), 1500);
  };

  const getTab = (jobId: string): ReviewTab =>
    activeTab[jobId] || "longform";

  const setTab = (jobId: string, tab: ReviewTab) =>
    setActiveTab((prev) => ({ ...prev, [jobId]: tab }));

  /* ─── Derived data helpers ─── */

  const getTitleVariants = (job: Job): string[] => {
    if (job.result?.title_variants && job.result.title_variants.length > 0)
      return job.result.title_variants;
    if (
      job.result?.seo_data?.long_form?.title_variants &&
      job.result.seo_data.long_form.title_variants.length > 0
    )
      return job.result.seo_data.long_form.title_variants;
    const single = job.result?.seo_data?.long_form?.title;
    return single ? [single] : [];
  };

  /* ─── Render ─── */

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Header */}
      <div className="border-b border-gray-800 px-8 py-4 flex justify-between items-center">
        <h1 className="text-2xl font-bold">YT Editor Pipeline</h1>
        <div className="flex items-center gap-4">
          {/* Asset status + upload */}
          {assetStatus && (
            <div className="flex items-center gap-2 text-xs">
              <label className={`cursor-pointer border rounded px-2 py-1 transition ${assetStatus.intro ? 'border-green-700 text-green-400' : 'border-red-700 text-red-400 hover:border-red-500'}`}>
                Intro {assetStatus.intro ? '✓' : '✗'}
                <input type="file" accept="video/*" className="hidden" onChange={async (e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  const fd = new FormData(); fd.append('file', file);
                  await fetch(`${API}/assets/intro`, { method: 'POST', body: fd });
                  fetchAssets();
                }} />
              </label>
              <label className={`cursor-pointer border rounded px-2 py-1 transition ${assetStatus.outro ? 'border-green-700 text-green-400' : 'border-red-700 text-red-400 hover:border-red-500'}`}>
                Outro {assetStatus.outro ? '✓' : '✗'}
                <input type="file" accept="video/*" className="hidden" onChange={async (e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  const fd = new FormData(); fd.append('file', file);
                  await fetch(`${API}/assets/outro`, { method: 'POST', body: fd });
                  fetchAssets();
                }} />
              </label>
            </div>
          )}
          <span
            className={
              authStatus.youtube
                ? "text-green-400 text-sm"
                : "text-red-400 text-sm"
            }
          >
            YouTube: {authStatus.youtube ? "Connected" : "Not connected"}
          </span>
          {!authStatus.youtube && (
            <a
              href="/auth/youtube"
              className="bg-red-600 hover:bg-red-700 px-4 py-2 rounded-lg text-sm font-semibold transition"
            >
              Connect YouTube
            </a>
          )}
        </div>
      </div>

      <div className="max-w-5xl mx-auto p-8">
        {/* Input Mode Tabs */}
        <div className="flex gap-1 mb-4 bg-gray-800 rounded-lg p-1">
          {[
            { key: "url" as InputMode, label: "Video URL / Upload", icon: "🎬" },
            { key: "avatar" as InputMode, label: "Avatar Video", icon: "🧑" },
            { key: "ugc" as InputMode, label: "UGC / Testimonial", icon: "📣" },
          ].map((tab) => (
            <button
              key={tab.key}
              onClick={() => setInputMode(tab.key)}
              className={`flex-1 py-2.5 px-4 rounded-md text-sm font-medium transition ${
                inputMode === tab.key
                  ? "bg-blue-600 text-white"
                  : "text-gray-400 hover:text-white hover:bg-gray-700"
              }`}
            >
              {tab.icon} {tab.label}
            </button>
          ))}
        </div>

        {/* URL / Upload Mode */}
        {inputMode === "url" && (
          <>
            <div className="flex gap-3 mb-4">
              <input
                type="text"
                value={videoUrl}
                onChange={(e) => setVideoUrl(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleUrlSubmit()}
                placeholder="Paste any video URL (Loom, YouTube, Vimeo, direct link)..."
                className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
              />
              <button
                onClick={handleUrlSubmit}
                disabled={loading}
                className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 px-6 py-3 rounded-lg font-semibold transition"
              >
                {loading ? "Processing..." : "Process URL"}
              </button>
            </div>

            {/* Advanced Options */}
            <details className="mb-4 bg-gray-800/50 border border-gray-700 rounded-xl">
              <summary className="px-4 py-3 cursor-pointer text-gray-300 hover:text-white font-medium text-sm">
                Options (description, template, instructions)
              </summary>
              <div className="px-4 pb-4 space-y-3">
                {/* Description Template Dropdown */}
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Description Template</label>
                  <div className="flex gap-2">
                    <select
                      value={descriptionTemplate ? "custom" : ""}
                      onChange={(e) => {
                        const val = e.target.value;
                        if (val === "" || val === "none") {
                          setDescriptionTemplate("");
                        } else if (val === "custom") {
                          // keep current
                        } else {
                          const t = savedTemplates.find((t) => t.id === val);
                          if (t) setDescriptionTemplate(t.content);
                        }
                      }}
                      className="flex-1 bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
                    >
                      <option value="none">No template</option>
                      {savedTemplates.map((t) => (
                        <option key={t.id} value={t.id}>{t.name}</option>
                      ))}
                    </select>
                  </div>
                  {/* Save new template */}
                  {descriptionTemplate && (
                    <div className="flex gap-2 mt-2">
                      <input
                        type="text"
                        value={newTemplateName}
                        onChange={(e) => setNewTemplateName(e.target.value)}
                        placeholder="Save as template..."
                        className="flex-1 bg-gray-900 border border-gray-600 rounded-lg px-3 py-1.5 text-white placeholder-gray-500 text-xs focus:outline-none focus:border-blue-500"
                      />
                      <button
                        onClick={async () => {
                          if (!newTemplateName.trim()) return;
                          await fetch(`${API}/templates`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ name: newTemplateName, content: descriptionTemplate }),
                          });
                          setNewTemplateName("");
                          fetchTemplates();
                        }}
                        className="bg-blue-600 hover:bg-blue-700 px-3 py-1.5 rounded-lg text-xs font-medium transition"
                      >
                        Save
                      </button>
                    </div>
                  )}
                  {/* Template preview/edit */}
                  <textarea
                    value={descriptionTemplate}
                    onChange={(e) => setDescriptionTemplate(e.target.value)}
                    placeholder={"Select a saved template or type one:\n---\nSubscribe: https://youtube.com/@YourChannel\nFree Resources: https://yoursite.com/free\n---"}
                    rows={3}
                    className="w-full mt-2 bg-gray-900 border border-gray-600 rounded-lg px-4 py-2 text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 resize-y text-sm"
                  />
                </div>

                {/* Custom Description */}
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Description (for this video)</label>
                  <textarea
                    value={customDescription}
                    onChange={(e) => setCustomDescription(e.target.value)}
                    placeholder="Add a custom description for this specific video. AI will enhance it with SEO optimization."
                    rows={3}
                    className="w-full bg-gray-900 border border-gray-600 rounded-lg px-4 py-3 text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 resize-y text-sm"
                  />
                </div>

                {/* Special Instructions */}
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Special Instructions (for the AI editors)</label>
                  <textarea
                    value={videoInstructions}
                    onChange={(e) => setVideoInstructions(e.target.value)}
                    placeholder="E.g., Keep the energy high, focus on actionable tips, target audience is entrepreneurs..."
                    rows={2}
                    className="w-full bg-gray-900 border border-gray-600 rounded-lg px-4 py-3 text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 resize-y text-sm"
                  />
                </div>
              </div>
            </details>

            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragActive(true);
              }}
              onDragLeave={() => setDragActive(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`mb-10 border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition ${
                dragActive
                  ? "border-blue-500 bg-blue-500/10"
                  : "border-gray-700 hover:border-gray-500"
              }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept="video/*"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleFileUpload(file);
                }}
              />
              {uploading ? (
                <p className="text-yellow-400">Uploading video...</p>
              ) : (
                <p className="text-gray-400">
                  Drop a video file here or click to upload (MP4, MOV, AVI, MKV, WebM)
                </p>
              )}
            </div>
          </>
        )}

        {/* Avatar Video Mode */}
        {inputMode === "avatar" && (
          <div className="mb-10 space-y-4">
            <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-6">
              <h3 className="text-lg font-semibold mb-1">Create Avatar Video</h3>
              <p className="text-gray-400 text-sm mb-4">
                Write a script and your AI avatar will deliver it. The video then goes through
                the full editing pipeline: captions, shorts, thumbnails, and publishing.
              </p>
              <textarea
                value={avatarScript}
                onChange={(e) => setAvatarScript(e.target.value)}
                placeholder="Write your script here. Your avatar will speak these exact words..."
                rows={6}
                className="w-full bg-gray-900 border border-gray-600 rounded-lg px-4 py-3 text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 resize-y"
              />
              <div className="flex gap-3 mt-3">
                <input
                  type="text"
                  value={avatarId}
                  onChange={(e) => setAvatarId(e.target.value)}
                  placeholder="Avatar ID (leave empty for default)"
                  className="flex-1 bg-gray-900 border border-gray-600 rounded-lg px-4 py-2.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
                />
                <button
                  onClick={handleAvatarSubmit}
                  disabled={loading || !avatarScript.trim()}
                  className="bg-purple-600 hover:bg-purple-700 disabled:opacity-50 px-6 py-2.5 rounded-lg font-semibold transition"
                >
                  {loading ? "Generating..." : "Generate Avatar Video"}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* UGC Mode — AI-Generated Authentic Content */}
        {inputMode === "ugc" && (
          <div className="mb-10 space-y-4">
            <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-6">
              <h3 className="text-lg font-semibold mb-1">Create AI UGC Video</h3>
              <p className="text-gray-400 text-sm mb-4">
                Describe your product or topic. AI agents will write the script, generate faces,
                animate scenes, add voiceover, and assemble a finished UGC video. ~$1-2 per video.
              </p>
              <div className="flex gap-3 mb-3">
                <select
                  value={ugcStyle}
                  onChange={(e) => setUgcStyle(e.target.value)}
                  className="bg-gray-900 border border-gray-600 rounded-lg px-4 py-2.5 text-sm text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="testimonial">Testimonial</option>
                  <option value="review">Product Review</option>
                  <option value="unboxing">Unboxing</option>
                  <option value="reaction">Reaction</option>
                </select>
                <select
                  value={ugcPersona}
                  onChange={(e) => setUgcPersona(e.target.value)}
                  className="bg-gray-900 border border-gray-600 rounded-lg px-4 py-2.5 text-sm text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="young professional">Young Professional</option>
                  <option value="college student">College Student</option>
                  <option value="busy parent">Busy Parent</option>
                  <option value="fitness enthusiast">Fitness Enthusiast</option>
                  <option value="tech enthusiast">Tech Enthusiast</option>
                  <option value="small business owner">Small Business Owner</option>
                </select>
                <select
                  value={ugcVoiceGender}
                  onChange={(e) => setUgcVoiceGender(e.target.value)}
                  className="bg-gray-900 border border-gray-600 rounded-lg px-4 py-2.5 text-sm text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="female">Female Voice</option>
                  <option value="male">Male Voice</option>
                </select>
                <select
                  value={ugcDuration}
                  onChange={(e) => setUgcDuration(Number(e.target.value))}
                  className="bg-gray-900 border border-gray-600 rounded-lg px-4 py-2.5 text-sm text-white focus:outline-none focus:border-blue-500"
                >
                  <option value={15}>15s</option>
                  <option value={30}>30s</option>
                  <option value={45}>45s</option>
                  <option value={60}>60s</option>
                </select>
              </div>
              <textarea
                value={ugcBrief}
                onChange={(e) => setUgcBrief(e.target.value)}
                placeholder={"Describe your product or topic. Be specific about what makes it unique.\n\nExample: Protein powder that dissolves instantly in cold water. No chalky texture. 30g protein per scoop. Used by busy professionals who work out before 6am."}
                rows={5}
                className="w-full bg-gray-900 border border-gray-600 rounded-lg px-4 py-3 text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 resize-y"
              />
              <div className="flex justify-end mt-3">
                <button
                  onClick={handleUgcSubmit}
                  disabled={loading || !ugcBrief.trim()}
                  className="bg-orange-600 hover:bg-orange-700 disabled:opacity-50 px-6 py-2.5 rounded-lg font-semibold transition"
                >
                  {loading ? "Generating..." : "Generate UGC Video"}
                </button>
              </div>
            </div>
          </div>
        )}

        {error && (
          <div className="bg-red-900/50 border border-red-700 rounded-lg p-3 mb-6 text-red-300">
            {error}
          </div>
        )}

        {/* Jobs */}
        {jobs.length === 0 ? (
          <div className="text-gray-500 text-center py-20">
            No videos processed yet. Paste a URL or upload a video above to get
            started.
          </div>
        ) : (
          <div className="space-y-6">
            {jobs.map((job) => {
              const r = job.result;
              const tab = getTab(job.id);
              const titleVariants = getTitleVariants(job);

              return (
                <div
                  key={job.id}
                  className="bg-gray-900 border border-gray-800 rounded-xl p-6"
                >
                  {/* Job Header */}
                  <div className="flex justify-between items-center mb-4">
                    <div className="flex items-center gap-3">
                      <span className="text-sm text-gray-400">
                        Job #{job.id}
                      </span>
                      <span
                        className={`text-xs px-2 py-1 rounded-full ${
                          job.status === "ready_for_review"
                            ? "bg-blue-900 text-blue-300"
                            : job.status === "published"
                            ? "bg-green-900 text-green-300"
                            : job.status === "failed"
                            ? "bg-red-900 text-red-300"
                            : "bg-yellow-900 text-yellow-300"
                        }`}
                      >
                        {job.status}
                      </span>
                      <span className="text-xs text-gray-600">
                        {job.source_type === "upload" ? "File upload" : "URL"}
                      </span>
                    </div>
                    <span className="text-xs text-gray-500">
                      {job.created_at}
                    </span>
                  </div>

                  <div className="text-sm text-gray-400 mb-4 truncate">
                    {job.source}
                  </div>

                  {/* Error */}
                  {job.status === "failed" && job.error && (
                    <div className="bg-red-900/30 border border-red-800 rounded-lg p-3 mb-4 text-red-300 text-sm">
                      {job.error}
                    </div>
                  )}

                  {/* Pipeline Steps */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4">
                    {Object.entries(job.steps).map(([key, val]) => (
                      <div
                        key={key}
                        className={`flex items-center gap-2 text-sm ${statusColor(
                          val
                        )}`}
                      >
                        <span
                          className="w-2 h-2 rounded-full inline-block"
                          style={{
                            backgroundColor:
                              val === "complete"
                                ? "#4ade80"
                                : val === "running"
                                ? "#facc15"
                                : "#374151",
                          }}
                        />
                        <span>{stepLabels[key] || key}</span>
                      </div>
                    ))}
                  </div>

                  {/* Stats Row */}
                  {r && (r.filler_count !== undefined || r.original_duration !== undefined) && (
                    <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-gray-400 mb-4 border-t border-gray-800 pt-3">
                      {r.filler_count !== undefined && (
                        <span>
                          Fillers:{" "}
                          <strong className="text-white">
                            {r.filler_count}
                          </strong>
                        </span>
                      )}
                      {r.dead_air_removed !== undefined && (
                        <span>
                          Dead air:{" "}
                          <strong className="text-white">
                            {r.dead_air_removed}
                          </strong>
                        </span>
                      )}
                      {r.tangents_removed !== undefined && (
                        <span>
                          Tangents:{" "}
                          <strong className="text-white">
                            {r.tangents_removed}
                          </strong>
                        </span>
                      )}
                      {r.word_count !== undefined && (
                        <span>
                          Words:{" "}
                          <strong className="text-white">
                            {r.word_count}
                          </strong>
                        </span>
                      )}
                      {r.original_duration !== undefined &&
                        r.edited_duration !== undefined && (
                          <span>
                            Duration:{" "}
                            <strong className="text-white">
                              {fmtDuration(r.original_duration)} &rarr;{" "}
                              {fmtDuration(r.edited_duration)}
                            </strong>
                            <span className="text-green-400 ml-1">
                              (saved{" "}
                              {fmtDuration(
                                r.original_duration - r.edited_duration
                              )}
                              )
                            </span>
                          </span>
                        )}
                    </div>
                  )}

                  {/* ───── Review Section (Tabbed) ───── */}
                  {job.status === "ready_for_review" && r && (
                    <div className="border-t border-gray-800 pt-4 space-y-4">
                      {/* Tab bar */}
                      <div className="flex border-b border-gray-700">
                        {TAB_LABELS.map((t) => (
                          <button
                            key={t.key}
                            onClick={() => setTab(job.id, t.key)}
                            className={`px-4 py-2 text-sm font-medium border-b-2 transition -mb-px ${
                              tab === t.key
                                ? "border-blue-500 text-blue-400"
                                : "border-transparent text-gray-500 hover:text-gray-300"
                            }`}
                          >
                            {t.label}
                          </button>
                        ))}
                      </div>

                      {/* ── Tab 1: Long-Form Video ── */}
                      {tab === "longform" && (
                        <div className="space-y-4">
                          {/* Edit Summary Card */}
                          {(r.original_duration !== undefined ||
                            r.filler_count !== undefined) && (
                            <div className="bg-gray-800 rounded-lg p-4 space-y-3">
                              <h4 className="text-sm font-semibold text-gray-300">
                                Edit Summary
                              </h4>
                              {r.original_duration !== undefined &&
                                r.edited_duration !== undefined && (
                                  <div className="text-sm text-gray-400">
                                    <span className="text-white">
                                      {fmtDuration(r.original_duration)}
                                    </span>{" "}
                                    &rarr;{" "}
                                    <span className="text-white">
                                      {fmtDuration(r.edited_duration)}
                                    </span>
                                    <span className="text-green-400 ml-2">
                                      (saved{" "}
                                      {fmtDuration(
                                        r.original_duration -
                                          r.edited_duration
                                      )}
                                      )
                                    </span>
                                  </div>
                                )}
                              <div className="text-sm text-gray-400">
                                Cuts:{" "}
                                <strong className="text-white">
                                  {r.filler_count ?? 0}
                                </strong>{" "}
                                fillers,{" "}
                                <strong className="text-white">
                                  {r.dead_air_removed ?? 0}
                                </strong>{" "}
                                dead air,{" "}
                                <strong className="text-white">
                                  {r.tangents_removed ?? 0}
                                </strong>{" "}
                                tangents removed
                              </div>
                              {r.edit_plan?.text_overlays !== undefined && (
                                <div className="text-sm text-gray-400">
                                  Text overlays added:{" "}
                                  <strong className="text-white">
                                    {Array.isArray(r.edit_plan.text_overlays)
                                      ? r.edit_plan.text_overlays.length
                                      : r.edit_plan.text_overlays}
                                  </strong>
                                </div>
                              )}
                              {r.edit_plan && (
                                <div className="text-sm text-gray-400">
                                  Intro:{" "}
                                  <strong className="text-white">
                                    {r.edit_plan.intro_added
                                      ? "Added"
                                      : "Skipped"}
                                  </strong>{" "}
                                  | Outro:{" "}
                                  <strong className="text-white">
                                    {r.edit_plan.outro_added
                                      ? "Added"
                                      : "Skipped"}
                                  </strong>
                                </div>
                              )}
                            </div>
                          )}

                          {/* Title Variants */}
                          {titleVariants.length > 0 && (
                            <div>
                              <h4 className="text-sm font-semibold text-gray-300 mb-2">
                                Select Title
                              </h4>
                              <div className="space-y-2">
                                {titleVariants.map((variant, i) => (
                                  <label
                                    key={i}
                                    className={`flex items-center gap-3 p-2 rounded-lg cursor-pointer transition ${
                                      (selectedTitles[job.id] ?? 0) === i
                                        ? "bg-blue-900/40 border border-blue-600"
                                        : "bg-gray-800 border border-gray-700 hover:border-gray-500"
                                    }`}
                                  >
                                    <input
                                      type="radio"
                                      name={`title-${job.id}`}
                                      checked={
                                        (selectedTitles[job.id] ?? 0) === i
                                      }
                                      onChange={() =>
                                        setSelectedTitles((prev) => ({
                                          ...prev,
                                          [job.id]: i,
                                        }))
                                      }
                                      className="accent-blue-500"
                                    />
                                    <span className="text-white text-sm font-medium">
                                      {variant}
                                    </span>
                                  </label>
                                ))}
                              </div>
                            </div>
                          )}

                          {/* Description Preview */}
                          {r.seo_data?.long_form?.description && (
                            <div>
                              <h4 className="text-sm font-semibold text-gray-300 mb-1">
                                Description
                              </h4>
                              <p className="text-sm text-gray-400 bg-gray-800 rounded-lg p-3">
                                {r.seo_data.long_form.description.substring(
                                  0,
                                  200
                                )}
                                {(r.seo_data.long_form.description.length ?? 0) >
                                200
                                  ? "..."
                                  : ""}
                              </p>
                            </div>
                          )}

                          {/* Tag Pills */}
                          {r.seo_data?.long_form?.tags &&
                            r.seo_data.long_form.tags.length > 0 && (
                              <div className="flex flex-wrap gap-1.5">
                                {r.seo_data.long_form.tags.map((tag, i) => (
                                  <span
                                    key={i}
                                    className="bg-gray-700 text-gray-300 text-xs px-2.5 py-1 rounded-full"
                                  >
                                    {tag}
                                  </span>
                                ))}
                              </div>
                            )}

                          {/* Thumbnail — single optimised thumbnail */}
                          {r.thumbnail_paths &&
                            r.thumbnail_paths.length > 0 && (() => {
                              const thumbFile = r.thumbnail_paths[0]?.split("/").pop();
                              return thumbFile ? (
                                <div>
                                  <h4 className="text-sm font-semibold text-gray-300 mb-2">
                                    Thumbnail
                                  </h4>
                                  <div className="rounded-xl overflow-hidden border-2 border-blue-500 ring-2 ring-blue-500/20 max-w-sm">
                                    <img
                                      src={`/api/thumbnails/${thumbFile}`}
                                      alt="Thumbnail"
                                      className="w-full aspect-video object-cover"
                                    />
                                  </div>
                                </div>
                              ) : null;
                            })()}
                        </div>
                      )}

                      {/* ── Tab 2: Shorts ── */}
                      {tab === "shorts" && (
                        <div className="space-y-3">
                          {r.short_designs && r.short_designs.length > 0 ? (
                            r.short_designs.map((sd: any, i: number) => {
                              const thumbPath =
                                r.short_thumbnail_paths?.[i];
                              const thumbFile = thumbPath
                                ? thumbPath.split("/").pop()
                                : null;
                              const hookScore =
                                sd.hook_strength ?? sd.hook_score ?? null;
                              return (
                                <div
                                  key={i}
                                  className="bg-gray-800 rounded-lg p-4 flex gap-4"
                                >
                                  {thumbFile && (
                                    <img
                                      src={`/api/thumbnails/${thumbFile}`}
                                      alt={`Short ${i + 1}`}
                                      className="w-24 h-14 rounded object-cover flex-shrink-0"
                                    />
                                  )}
                                  <div className="flex-1 min-w-0 space-y-1">
                                    <div className="flex items-center gap-2 flex-wrap">
                                      <span className="text-white text-sm font-medium truncate">
                                        {sd.title ||
                                          `Short ${i + 1}`}
                                      </span>
                                      {sd.duration !== undefined && (
                                        <span className="text-xs px-2 py-0.5 rounded-full bg-gray-700 text-gray-300">
                                          {Math.round(sd.duration)}s
                                        </span>
                                      )}
                                      {hookScore !== null && (
                                        <span
                                          className={`text-xs px-2 py-0.5 rounded-full ${
                                            hookBadge(hookScore).cls
                                          }`}
                                        >
                                          {hookBadge(hookScore).text}
                                        </span>
                                      )}
                                    </div>
                                    {sd.description && (
                                      <p className="text-xs text-gray-400 truncate">
                                        {sd.description}
                                      </p>
                                    )}
                                  </div>
                                </div>
                              );
                            })
                          ) : r.short_paths && r.short_paths.length > 0 ? (
                            r.short_paths.map((sp, i) => {
                              const thumbPath =
                                r.short_thumbnail_paths?.[i];
                              const thumbFile =
                                thumbPath
                                  ? thumbPath.split("/").pop()
                                  : null;
                              const seoShort = r.seo_data?.shorts?.[i];
                              return (
                                <div
                                  key={i}
                                  className="bg-gray-800 rounded-lg p-4 flex gap-4"
                                >
                                  {thumbFile && (
                                    <img
                                      src={`/api/thumbnails/${thumbFile}`}
                                      alt={`Short ${i + 1}`}
                                      className="w-24 h-14 rounded object-cover flex-shrink-0"
                                    />
                                  )}
                                  <div className="flex-1 min-w-0">
                                    <span className="text-white text-sm font-medium block truncate">
                                      {seoShort?.title || `Short ${i + 1}`}
                                    </span>
                                    {seoShort?.description && (
                                      <p className="text-xs text-gray-400 mt-1 truncate">
                                        {seoShort.description}
                                      </p>
                                    )}
                                  </div>
                                </div>
                              );
                            })
                          ) : (
                            <div className="text-gray-500 text-sm text-center py-6">
                              No shorts generated yet.
                            </div>
                          )}
                        </div>
                      )}

                      {/* ── Tab 3: Community Posts (Ready-to-Copy Cards) ── */}
                      {tab === "community" && (
                        <div className="space-y-4">
                          {r.community_posts &&
                          r.community_posts.length > 0 ? (
                            <>
                              <p className="text-gray-400 text-xs">
                                {r.community_posts.length} post{r.community_posts.length > 1 ? "s" : ""} ready to copy
                              </p>
                              {r.community_posts.map(
                                (
                                  post: { text: string; type: string; frame_image?: string; ai_image?: string },
                                  pi: number
                                ) => {
                                  const copyKey = `${job.id}-cp-${pi}`;
                                  const hasImage = !!(post.frame_image || post.ai_image);
                                  return (
                                    <div
                                      key={pi}
                                      className="bg-gray-800 border border-gray-700 rounded-xl p-5 space-y-3"
                                    >
                                      {/* Header: badge + image note */}
                                      <div className="flex items-center gap-2 flex-wrap">
                                        <span
                                          className={`text-xs font-medium px-2.5 py-1 rounded-full ${typeBadgeColor(
                                            post.type
                                          )}`}
                                        >
                                          {post.type.replace(/_/g, " ")}
                                        </span>
                                        {hasImage && (
                                          <span className="text-xs text-amber-400 bg-amber-400/10 px-2.5 py-1 rounded-full">
                                            Image available in thumbnails
                                          </span>
                                        )}
                                      </div>

                                      {/* Post text */}
                                      <p className="text-white text-sm leading-relaxed whitespace-pre-wrap">
                                        {post.text}
                                      </p>

                                      {/* Copy button */}
                                      <div className="pt-1">
                                        <button
                                          onClick={() =>
                                            handleCopy(post.text, copyKey)
                                          }
                                          className={`w-full sm:w-auto px-5 py-2 rounded-lg text-sm font-medium transition-all ${
                                            copiedIdx === copyKey
                                              ? "bg-green-600 text-white"
                                              : "bg-indigo-600 hover:bg-indigo-500 text-white"
                                          }`}
                                        >
                                          {copiedIdx === copyKey
                                            ? "Copied!"
                                            : "Copy to Clipboard"}
                                        </button>
                                      </div>
                                    </div>
                                  );
                                }
                              )}
                              <p className="text-gray-500 text-xs mt-2">
                                Paste into YouTube Studio &rarr; Community tab
                              </p>
                            </>
                          ) : (
                            <div className="text-gray-500 text-sm text-center py-6">
                              No community posts generated.
                            </div>
                          )}
                        </div>
                      )}

                      {/* ── Tab 4: QA Report ── */}
                      {tab === "qa" && (
                        <div className="space-y-4">
                          {r.qa_scores ? (
                            <>
                              {/* Pass / Fail */}
                              <div className="flex items-center gap-3">
                                <span className="text-sm font-semibold text-gray-300">
                                  Overall:
                                </span>
                                <span
                                  className={`text-sm font-bold px-3 py-1 rounded-full ${
                                    r.qa_scores.passed
                                      ? "bg-green-900 text-green-300"
                                      : "bg-red-900 text-red-300"
                                  }`}
                                >
                                  {r.qa_scores.passed ? "PASS" : "FAIL"}
                                </span>
                              </div>

                              {/* Score bars */}
                              <div className="space-y-3 bg-gray-800 rounded-lg p-4">
                                {r.qa_scores.coherence_score !== undefined && (
                                  <ProgressBar
                                    value={r.qa_scores.coherence_score}
                                    max={10}
                                    label="Coherence"
                                  />
                                )}
                                {r.qa_scores.engagement_prediction !==
                                  undefined && (
                                  <ProgressBar
                                    value={r.qa_scores.engagement_prediction}
                                    max={10}
                                    label="Engagement"
                                  />
                                )}
                                {r.qa_scores.seo_score !== undefined && (
                                  <ProgressBar
                                    value={r.qa_scores.seo_score}
                                    max={10}
                                    label="SEO"
                                  />
                                )}
                                {r.qa_scores.total_score !== undefined && (
                                  <div className="border-t border-gray-700 pt-2 mt-2 text-sm flex justify-between">
                                    <span className="text-gray-400 font-medium">
                                      Total
                                    </span>
                                    <span className="text-white font-bold">
                                      {r.qa_scores.total_score}/30
                                    </span>
                                  </div>
                                )}
                              </div>

                              {/* Issues */}
                              {r.qa_scores.issues &&
                                r.qa_scores.issues.length > 0 && (
                                  <div>
                                    <h4 className="text-sm font-semibold text-red-400 mb-1">
                                      Issues
                                    </h4>
                                    <ul className="list-disc list-inside text-sm text-gray-400 space-y-0.5">
                                      {r.qa_scores.issues.map((iss, i) => (
                                        <li key={i}>{iss}</li>
                                      ))}
                                    </ul>
                                  </div>
                                )}

                              {/* Suggestions */}
                              {r.qa_scores.suggestions &&
                                r.qa_scores.suggestions.length > 0 && (
                                  <div>
                                    <h4 className="text-sm font-semibold text-yellow-400 mb-1">
                                      Suggestions
                                    </h4>
                                    <ul className="list-disc list-inside text-sm text-gray-400 space-y-0.5">
                                      {r.qa_scores.suggestions.map(
                                        (sug, i) => (
                                          <li key={i}>{sug}</li>
                                        )
                                      )}
                                    </ul>
                                  </div>
                                )}

                              {/* Per-short scores table */}
                              {r.qa_scores.short_scores &&
                                r.qa_scores.short_scores.length > 0 && (
                                  <div>
                                    <h4 className="text-sm font-semibold text-gray-300 mb-2">
                                      Per-Short Scores
                                    </h4>
                                    <div className="overflow-x-auto">
                                      <table className="w-full text-sm">
                                        <thead>
                                          <tr className="text-gray-500 text-xs border-b border-gray-700">
                                            <th className="text-left py-2 pr-4">
                                              Short
                                            </th>
                                            <th className="text-right py-2 px-2">
                                              Coherence
                                            </th>
                                            <th className="text-right py-2 px-2">
                                              Engagement
                                            </th>
                                            <th className="text-right py-2 px-2">
                                              SEO
                                            </th>
                                          </tr>
                                        </thead>
                                        <tbody>
                                          {r.qa_scores.short_scores.map(
                                            (ss) => (
                                              <tr
                                                key={ss.index}
                                                className="border-b border-gray-800"
                                              >
                                                <td className="py-2 pr-4 text-gray-300">
                                                  Short {ss.index + 1}
                                                </td>
                                                <td
                                                  className={`py-2 px-2 text-right font-medium ${scoreTextColor(
                                                    ss.coherence
                                                  )}`}
                                                >
                                                  {ss.coherence}
                                                </td>
                                                <td
                                                  className={`py-2 px-2 text-right font-medium ${scoreTextColor(
                                                    ss.engagement
                                                  )}`}
                                                >
                                                  {ss.engagement}
                                                </td>
                                                <td
                                                  className={`py-2 px-2 text-right font-medium ${scoreTextColor(
                                                    ss.seo
                                                  )}`}
                                                >
                                                  {ss.seo}
                                                </td>
                                              </tr>
                                            )
                                          )}
                                        </tbody>
                                      </table>
                                    </div>
                                  </div>
                                )}
                            </>
                          ) : (
                            <div className="text-gray-500 text-sm text-center py-6">
                              No QA data available.
                            </div>
                          )}
                        </div>
                      )}

                      {/* ── Schedule + Approve ── */}
                      <div className="space-y-2 border-t border-gray-800 pt-4">
                        <div className="flex items-center gap-4">
                          <input
                            type="datetime-local"
                            value={publishTimes[job.id] || ""}
                            onChange={(e) =>
                              setPublishTimes((prev) => ({
                                ...prev,
                                [job.id]: e.target.value,
                              }))
                            }
                            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white"
                          />
                          <button
                            onClick={() => handleApprove(job.id)}
                            disabled={!!approving[job.id]}
                            className={`flex-1 py-2 rounded-lg font-semibold transition ${
                              approving[job.id] === "done"
                                ? "bg-green-700 cursor-default"
                                : approving[job.id]
                                ? "bg-yellow-600 cursor-wait animate-pulse"
                                : "bg-green-600 hover:bg-green-700"
                            }`}
                          >
                            {approving[job.id] === "done"
                              ? "Published \u2713"
                              : approving[job.id]
                              ? approving[job.id]
                              : "Approve and Upload to YouTube"}
                          </button>
                        </div>
                        {approveErrors[job.id] && (
                          <div className="text-red-400 text-sm bg-red-900/30 border border-red-800 rounded-lg p-2 flex justify-between items-center">
                            <span>{approveErrors[job.id]}</span>
                            <button
                              onClick={() => {
                                setApproveErrors((prev) => {
                                  const next = { ...prev };
                                  delete next[job.id];
                                  return next;
                                });
                                handleApprove(job.id);
                              }}
                              className="bg-red-800 hover:bg-red-700 px-3 py-1 rounded text-xs ml-3 flex-shrink-0"
                            >
                              Retry
                            </button>
                          </div>
                        )}
                        {approving[job.id] === "done" &&
                          job.youtube_video_id && (
                            <div className="flex flex-wrap gap-3 text-sm">
                              <a
                                href={`https://youtube.com/watch?v=${job.youtube_video_id}`}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-blue-400 hover:underline"
                              >
                                Long-form on YouTube
                              </a>
                              {job.youtube_short_ids?.map((sid, i) => (
                                <a
                                  key={i}
                                  href={`https://youtube.com/shorts/${sid}`}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="text-blue-400 hover:underline"
                                >
                                  Short {i + 1}
                                </a>
                              ))}
                            </div>
                          )}
                      </div>
                    </div>
                  )}

                  {/* ───── Published Section ───── */}
                  {job.status === "published" && (
                    <div className="border-t border-gray-800 pt-4 space-y-3">
                      <div className="flex items-center gap-2">
                        <span className="text-green-400 font-semibold">
                          Published &#10003;
                        </span>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {job.youtube_video_id && (
                          <a
                            href={`https://youtube.com/watch?v=${job.youtube_video_id}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 bg-red-900/40 hover:bg-red-900/60 text-red-300 px-3 py-1.5 rounded-lg text-sm transition"
                          >
                            <span>&#9654;</span> View Long-Form on YouTube
                          </a>
                        )}
                        {job.youtube_short_ids?.map((sid, i) => (
                          <a
                            key={i}
                            href={`https://youtube.com/shorts/${sid}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 bg-blue-900/40 hover:bg-blue-900/60 text-blue-300 px-3 py-1.5 rounded-lg text-sm transition"
                          >
                            <span>&#9654;</span> Short {i + 1} on YouTube
                          </a>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
