"use client";

import { useState, useEffect, useRef } from "react";

interface JobStep {
  [key: string]: string;
}

interface SeoData {
  long_form?: { title?: string; description?: string; tags?: string[] };
  shorts?: { title?: string; description?: string; tags?: string[] }[];
}

interface JobResult {
  video_path?: string;
  short_paths?: string[];
  shorts_config?: { start: number; end: number; title: string }[];
  seo_data?: SeoData;
  thumbnail_paths?: string[];
  filler_count?: number;
  word_count?: number;
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

const API = "/api";

const stepLabels: Record<string, string> = {
  download: "Downloaded",
  transcribe: "Transcribed",
  filler_removal: "Filler removed",
  short_detection: "Shorts detected",
  short_creation: "Shorts created",
  seo_generation: "SEO generated",
  thumbnail_generation: "Thumbnails ready",
};

const statusColor = (s: string) =>
  s === "complete"
    ? "text-green-400"
    : s === "running"
    ? "text-yellow-400"
    : "text-gray-600";

export default function Home() {
  const [videoUrl, setVideoUrl] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [authStatus, setAuthStatus] = useState<AuthStatus>({ youtube: false });
  const [selectedThumbs, setSelectedThumbs] = useState<Record<string, number>>(
    {}
  );
  const [publishTimes, setPublishTimes] = useState<Record<string, string>>({});
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchJobs = async () => {
    try {
      const res = await fetch(`${API}/jobs`);
      const data = await res.json();
      setJobs((data.jobs || []).reverse());
    } catch {
      /* polling */
    }
  };

  const fetchAuth = async () => {
    try {
      const res = await fetch(`/auth/status`);
      setAuthStatus(await res.json());
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    fetchJobs();
    fetchAuth();
    const interval = setInterval(fetchJobs, 3000);
    return () => clearInterval(interval);
  }, []);

  const handleUrlSubmit = async () => {
    if (!videoUrl.trim()) return;
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API}/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_url: videoUrl }),
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
    try {
      const res = await fetch(`${API}/jobs/${jobId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          publish_at: publishTimes[jobId] || "",
          selected_thumbnail: selectedThumbs[jobId] || 0,
        }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Approval failed");
      }
      await fetchJobs();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approval failed");
    }
  };

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Header */}
      <div className="border-b border-gray-800 px-8 py-4 flex justify-between items-center">
        <h1 className="text-2xl font-bold">YT Editor Pipeline</h1>
        <div className="flex items-center gap-4">
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
        {/* URL Input */}
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

        {/* File Upload / Drag & Drop */}
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
              Drop a video file here or click to upload (MP4, MOV, AVI, MKV,
              WebM)
            </p>
          )}
        </div>

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
            {jobs.map((job) => (
              <div
                key={job.id}
                className="bg-gray-900 border border-gray-800 rounded-xl p-6"
              >
                {/* Header */}
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

                {/* Stats */}
                {job.result && job.result.filler_count !== undefined && (
                  <div className="flex gap-6 text-sm text-gray-400 mb-4 border-t border-gray-800 pt-3">
                    <span>
                      Fillers removed:{" "}
                      <strong className="text-white">
                        {job.result.filler_count}
                      </strong>
                    </span>
                    <span>
                      Words:{" "}
                      <strong className="text-white">
                        {job.result.word_count}
                      </strong>
                    </span>
                    <span>
                      Shorts:{" "}
                      <strong className="text-white">
                        {job.result.short_paths?.length || 0}
                      </strong>
                    </span>
                  </div>
                )}

                {/* Review Section */}
                {job.status === "ready_for_review" && job.result && (
                  <div className="border-t border-gray-800 pt-4 space-y-4">
                    {/* SEO Preview */}
                    {job.result.seo_data?.long_form && (
                      <div>
                        <h3 className="text-sm font-semibold text-gray-300 mb-2">
                          Long-form SEO
                        </h3>
                        <div className="bg-gray-800 rounded-lg p-3 space-y-2">
                          <div className="text-white font-medium">
                            {job.result.seo_data.long_form.title}
                          </div>
                          <div className="text-gray-400 text-sm whitespace-pre-wrap">
                            {job.result.seo_data.long_form.description?.substring(
                              0,
                              200
                            )}
                            ...
                          </div>
                          <div className="flex flex-wrap gap-1">
                            {job.result.seo_data.long_form.tags
                              ?.slice(0, 8)
                              .map((tag, i) => (
                                <span
                                  key={i}
                                  className="bg-gray-700 text-gray-300 text-xs px-2 py-0.5 rounded"
                                >
                                  {tag}
                                </span>
                              ))}
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Thumbnails */}
                    {job.result.thumbnail_paths &&
                      job.result.thumbnail_paths.length > 0 && (
                        <div>
                          <h3 className="text-sm font-semibold text-gray-300 mb-2">
                            Select Thumbnail
                          </h3>
                          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                            {job.result.thumbnail_paths.map((path, i) => {
                              const filename = path.split("/").pop();
                              return (
                                <div
                                  key={i}
                                  onClick={() =>
                                    setSelectedThumbs((prev) => ({
                                      ...prev,
                                      [job.id]: i,
                                    }))
                                  }
                                  className={`cursor-pointer rounded-lg overflow-hidden border-2 transition ${
                                    (selectedThumbs[job.id] || 0) === i
                                      ? "border-blue-500"
                                      : "border-gray-700"
                                  }`}
                                >
                                  <img
                                    src={`/api/thumbnails/${filename}`}
                                    alt={`Thumbnail ${i + 1}`}
                                    className="w-full aspect-video object-cover"
                                  />
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}

                    {/* Shorts Preview */}
                    {job.result.shorts_config && (
                      <div>
                        <h3 className="text-sm font-semibold text-gray-300 mb-2">
                          Shorts ({job.result.shorts_config.length})
                        </h3>
                        <div className="space-y-2">
                          {job.result.shorts_config.map((s, i) => (
                            <div
                              key={i}
                              className="bg-gray-800 rounded-lg p-3 flex justify-between items-center"
                            >
                              <div>
                                <span className="text-white text-sm">
                                  {s.title}
                                </span>
                                <span className="text-gray-500 text-xs ml-2">
                                  {Math.round(s.end - s.start)}s
                                </span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Schedule + Approve */}
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
                        className="flex-1 bg-green-600 hover:bg-green-700 py-2 rounded-lg font-semibold transition"
                      >
                        Approve and Upload to YouTube
                      </button>
                    </div>
                  </div>
                )}

                {/* Published */}
                {job.status === "published" && (
                  <div className="border-t border-gray-800 pt-4">
                    <div className="flex items-center gap-2 text-green-400">
                      <span>Published</span>
                      {job.youtube_video_id && (
                        <a
                          href={`https://youtube.com/watch?v=${job.youtube_video_id}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-400 hover:underline text-sm"
                        >
                          View on YouTube
                        </a>
                      )}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
