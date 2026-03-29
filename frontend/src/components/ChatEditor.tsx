"use client";

import { useState, useEffect, useRef, useCallback } from "react";

/* ─── Types ─── */

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  attachments?: Attachment[];
}

interface Attachment {
  type: "file" | "url";
  value: string;
  name?: string;
}

interface SSEEvent {
  type: "token" | "done" | "error";
  content?: string;
}

interface ChatEditorProps {
  onJobCreated: (jobId: string) => void;
}

const API = "/api/chat";

const WELCOME_MESSAGE: ChatMessage = {
  role: "assistant",
  content:
    "Hey! I'm your video editor. Drop a video link or upload a file, and tell me what you're looking for. I'll handle the rest.",
  timestamp: Date.now(),
};

/* ─── Component ─── */

export default function ChatEditor({ onJobCreated }: ChatEditorProps) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME_MESSAGE]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [attachment, setAttachment] = useState<Attachment | null>(null);
  const [showUrlInput, setShowUrlInput] = useState(false);
  const [urlInput, setUrlInput] = useState("");

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  /* ─── Session creation ─── */

  useEffect(() => {
    fetch(`${API}/sessions`, { method: "POST" })
      .then((res) => res.json())
      .then((data) => setSessionId(data.session_id))
      .catch((err) => console.error("Failed to create chat session:", err));
  }, []);

  /* ─── Auto-scroll ─── */

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  /* ─── Readiness check ─── */

  const isReady = useCallback(() => {
    const lastAssistant = [...messages]
      .reverse()
      .find((m) => m.role === "assistant");
    if (!lastAssistant) return false;
    const lower = lastAssistant.content.toLowerCase();
    return lower.includes("ready") || lower.includes("start");
  }, [messages]);

  /* ─── Send message ─── */

  const sendMessage = useCallback(async () => {
    const content = input.trim();
    if (!content || !sessionId || isStreaming) return;

    const attachments = attachment
      ? [{ type: attachment.type, value: attachment.value }]
      : undefined;

    const userMessage: ChatMessage = {
      role: "user",
      content,
      timestamp: Date.now(),
      attachments: attachment ? [attachment] : undefined,
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setAttachment(null);
    setIsStreaming(true);

    // Add placeholder assistant message
    const assistantMessage: ChatMessage = {
      role: "assistant",
      content: "",
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, assistantMessage]);

    try {
      const response = await fetch(
        `${API}/sessions/${sessionId}/messages`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content, attachments }),
        }
      );

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body!.getReader();
      const decoder = new TextDecoder();
      let assistantContent = "";
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        // Keep the last potentially incomplete line in the buffer
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const payload = line.slice(6).trim();
          if (!payload || payload === "[DONE]") continue;

          try {
            const event: SSEEvent = JSON.parse(payload);
            if (event.type === "token" && event.content) {
              assistantContent += event.content;
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                  ...updated[updated.length - 1],
                  content: assistantContent,
                };
                return updated;
              });
            }
          } catch {
            // Skip malformed SSE lines
          }
        }
      }

      // Process any remaining buffer
      if (buffer.startsWith("data: ")) {
        const payload = buffer.slice(6).trim();
        if (payload && payload !== "[DONE]") {
          try {
            const event: SSEEvent = JSON.parse(payload);
            if (event.type === "token" && event.content) {
              assistantContent += event.content;
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                  ...updated[updated.length - 1],
                  content: assistantContent,
                };
                return updated;
              });
            }
          } catch {
            // Skip
          }
        }
      }
    } catch (err) {
      console.error("Chat stream error:", err);
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content: "Sorry, something went wrong. Please try again.",
        };
        return updated;
      });
    } finally {
      setIsStreaming(false);
    }
  }, [input, sessionId, isStreaming, attachment]);

  /* ─── Start editing ─── */

  const startEditing = useCallback(async () => {
    if (!sessionId || isStarting) return;
    setIsStarting(true);
    try {
      const res = await fetch(`${API}/sessions/${sessionId}/start`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      onJobCreated(data.job_id);
    } catch (err) {
      console.error("Failed to start editing:", err);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Failed to start the editing pipeline. Please try again.",
          timestamp: Date.now(),
        },
      ]);
    } finally {
      setIsStarting(false);
    }
  }, [sessionId, isStarting, onJobCreated]);

  /* ─── File attachment ─── */

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      // Create a local URL for preview; actual upload handled by the API on send
      const url = URL.createObjectURL(file);
      setAttachment({ type: "file", value: url, name: file.name });
      // Reset the input so the same file can be re-selected
      e.target.value = "";
    },
    []
  );

  const handleUrlAttach = useCallback(() => {
    const trimmed = urlInput.trim();
    if (!trimmed) return;
    setAttachment({ type: "url", value: trimmed, name: trimmed });
    setUrlInput("");
    setShowUrlInput(false);
  }, [urlInput]);

  const removeAttachment = useCallback(() => {
    setAttachment(null);
  }, []);

  /* ─── Key handler ─── */

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    },
    [sendMessage]
  );

  /* ─── Format timestamp ─── */

  const formatTime = (ts: number) => {
    const d = new Date(ts);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };

  /* ─── Render ─── */

  return (
    <div className="flex flex-col h-full bg-gray-950 rounded-xl border border-gray-800 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-gray-800 bg-gray-900/50">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center">
            <svg
              className="w-4 h-4 text-white"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"
              />
            </svg>
          </div>
          <div>
            <h3 className="text-sm font-semibold text-white">AI Editor</h3>
            <p className="text-xs text-gray-400">
              {isStreaming ? "Typing..." : "Online"}
            </p>
          </div>
        </div>

        {isReady() && (
          <button
            onClick={startEditing}
            disabled={isStarting}
            className="px-4 py-2 bg-green-600 hover:bg-green-500 disabled:bg-green-800 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors flex items-center gap-2"
          >
            {isStarting ? (
              <svg
                className="w-4 h-4 animate-spin"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
            ) : (
              <svg
                className="w-4 h-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"
                />
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
            )}
            {isStarting ? "Starting..." : "Start Editing"}
          </button>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4 scrollbar-thin scrollbar-thumb-gray-700">
        {messages.map((msg, i) => (
          <div
            key={`${msg.timestamp}-${i}`}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[75%] rounded-2xl px-4 py-3 ${
                msg.role === "user"
                  ? "bg-blue-600 text-white rounded-br-md"
                  : "bg-gray-800 text-gray-100 rounded-bl-md"
              }`}
            >
              {/* Attachments */}
              {msg.attachments && msg.attachments.length > 0 && (
                <div className="mb-2 space-y-1">
                  {msg.attachments.map((att, j) => (
                    <div
                      key={j}
                      className={`flex items-center gap-2 text-xs px-2 py-1 rounded ${
                        msg.role === "user"
                          ? "bg-blue-500/40"
                          : "bg-gray-700/60"
                      }`}
                    >
                      {att.type === "file" ? (
                        <svg
                          className="w-3 h-3 flex-shrink-0"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                          strokeWidth={2}
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"
                          />
                        </svg>
                      ) : (
                        <svg
                          className="w-3 h-3 flex-shrink-0"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                          strokeWidth={2}
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"
                          />
                        </svg>
                      )}
                      <span className="truncate">
                        {att.name || att.value}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {/* Message content */}
              <p className="text-sm whitespace-pre-wrap leading-relaxed">
                {msg.content}
                {isStreaming &&
                  i === messages.length - 1 &&
                  msg.role === "assistant" && (
                    <span className="inline-block w-1.5 h-4 bg-gray-400 ml-0.5 animate-pulse rounded-sm" />
                  )}
              </p>

              <p
                className={`text-[10px] mt-1.5 ${
                  msg.role === "user" ? "text-blue-200" : "text-gray-500"
                }`}
              >
                {formatTime(msg.timestamp)}
              </p>
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Attachment preview */}
      {attachment && (
        <div className="px-4 pb-1">
          <div className="flex items-center gap-2 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-300">
            {attachment.type === "file" ? (
              <svg
                className="w-4 h-4 text-gray-400 flex-shrink-0"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"
                />
              </svg>
            ) : (
              <svg
                className="w-4 h-4 text-gray-400 flex-shrink-0"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"
                />
              </svg>
            )}
            <span className="truncate flex-1">
              {attachment.name || attachment.value}
            </span>
            <button
              onClick={removeAttachment}
              className="text-gray-500 hover:text-gray-300 transition-colors flex-shrink-0"
            >
              <svg
                className="w-4 h-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M6 18L18 6M6 6l12 12"
                />
              </svg>
            </button>
          </div>
        </div>
      )}

      {/* URL input overlay */}
      {showUrlInput && (
        <div className="px-4 pb-1">
          <div className="flex items-center gap-2 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2">
            <input
              type="text"
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handleUrlAttach();
                }
                if (e.key === "Escape") {
                  setShowUrlInput(false);
                  setUrlInput("");
                }
              }}
              placeholder="Paste a video URL..."
              className="flex-1 bg-transparent text-sm text-white placeholder-gray-500 outline-none"
              autoFocus
            />
            <button
              onClick={handleUrlAttach}
              disabled={!urlInput.trim()}
              className="text-blue-400 hover:text-blue-300 disabled:text-gray-600 text-sm font-medium transition-colors"
            >
              Attach
            </button>
            <button
              onClick={() => {
                setShowUrlInput(false);
                setUrlInput("");
              }}
              className="text-gray-500 hover:text-gray-300 transition-colors"
            >
              <svg
                className="w-4 h-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M6 18L18 6M6 6l12 12"
                />
              </svg>
            </button>
          </div>
        </div>
      )}

      {/* Input bar */}
      <div className="px-4 py-3 border-t border-gray-800 bg-gray-900/50">
        <div className="flex items-end gap-2">
          {/* Attachment button with dropdown */}
          <div className="relative">
            <input
              ref={fileInputRef}
              type="file"
              accept="video/*,audio/*,.mp4,.mov,.avi,.mkv,.webm,.mp3,.wav"
              onChange={handleFileSelect}
              className="hidden"
            />
            <button
              onClick={() => {
                if (showUrlInput) {
                  setShowUrlInput(false);
                  setUrlInput("");
                }
                // Show a choice: file picker or URL input
                // Simple approach: click opens file picker, long-press / right-click for URL
                // For simplicity, alternate between the two or use a small menu
                fileInputRef.current?.click();
              }}
              onContextMenu={(e) => {
                e.preventDefault();
                setShowUrlInput(true);
              }}
              title="Attach file (right-click for URL)"
              className="p-2 text-gray-400 hover:text-gray-200 transition-colors rounded-lg hover:bg-gray-800"
            >
              <svg
                className="w-5 h-5"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"
                />
              </svg>
            </button>
            {/* URL shortcut button */}
            <button
              onClick={() => setShowUrlInput((v) => !v)}
              title="Attach URL"
              className="p-2 text-gray-400 hover:text-gray-200 transition-colors rounded-lg hover:bg-gray-800"
            >
              <svg
                className="w-5 h-5"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"
                />
              </svg>
            </button>
          </div>

          {/* Text input */}
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              sessionId
                ? "Describe your edit..."
                : "Connecting..."
            }
            disabled={!sessionId || isStreaming}
            rows={1}
            className="flex-1 bg-gray-800 text-white text-sm placeholder-gray-500 rounded-xl px-4 py-2.5 resize-none outline-none focus:ring-1 focus:ring-blue-500/50 border border-gray-700 disabled:opacity-50 max-h-32 overflow-y-auto"
            style={{ minHeight: "40px" }}
            onInput={(e) => {
              const target = e.target as HTMLTextAreaElement;
              target.style.height = "40px";
              target.style.height = `${Math.min(target.scrollHeight, 128)}px`;
            }}
          />

          {/* Send button */}
          <button
            onClick={sendMessage}
            disabled={!input.trim() || !sessionId || isStreaming}
            className="p-2.5 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:cursor-not-allowed text-white rounded-xl transition-colors flex-shrink-0"
          >
            <svg
              className="w-5 h-5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 19V5m0 0l-7 7m7-7l7 7"
              />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
