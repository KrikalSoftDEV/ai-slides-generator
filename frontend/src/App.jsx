import { useState, useCallback, useRef } from "react";
import EditableContent from "./EditableContent";

const ACCEPTED_TYPES = [
  "application/pdf",
  "image/png",
  "image/jpeg",
  "image/jpg",
  "image/webp",
  "image/gif",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
];

function isAcceptedSource(file) {
  const name = file.name.toLowerCase();
  return (
    ACCEPTED_TYPES.includes(file.type) ||
    file.type.startsWith("image/") ||
    name.endsWith(".pdf") ||
    name.endsWith(".pptx")
  );
}

function FileIcon({ type }) {
  if (type === "application/pdf") {
    return (
      <svg
        width="20"
        height="20"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      >
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
        <line x1="16" y1="13" x2="8" y2="13" />
        <line x1="16" y1="17" x2="8" y2="17" />
        <polyline points="10 9 9 9 8 9" />
      </svg>
    );
  }
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
    >
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
      <circle cx="8.5" cy="8.5" r="1.5" />
      <polyline points="21 15 16 10 5 21" />
    </svg>
  );
}

function UploadIcon() {
  return (
    <svg
      width="48"
      height="48"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
    >
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" y1="3" x2="12" y2="15" />
    </svg>
  );
}

function Spinner() {
  return (
    <svg
      className="spinner"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
    >
      <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
    </svg>
  );
}

export default function App() {
  const [activeTab, setActiveTab] = useState("edit"); // 'generate' or 'edit'
  const [files, setFiles] = useState([]);
  const [numSlides, setNumSlides] = useState(8);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [downloadUrl, setDownloadUrl] = useState(null);
  const [downloadName, setDownloadName] = useState("");
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef(null);

  const addFiles = useCallback((newFiles) => {
    const valid = Array.from(newFiles).filter(isAcceptedSource);
    if (valid.length < newFiles.length) {
      setError(
        "Some files were skipped — only PDF, image, and PPTX files are supported.",
      );
    }
    setFiles((prev) => {
      const existing = new Set(prev.map((f) => f.name + f.size));
      const unique = valid.filter((f) => !existing.has(f.name + f.size));
      return [...prev, ...unique];
    });
    setDownloadUrl(null);
    setError(null);
  }, []);

  const removeFile = (index) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
    setDownloadUrl(null);
  };

  const onDrop = useCallback(
    (e) => {
      e.preventDefault();
      setDragging(false);
      addFiles(e.dataTransfer.files);
    },
    [addFiles],
  );

  const onDragOver = (e) => {
    e.preventDefault();
    setDragging(true);
  };

  const onDragLeave = () => setDragging(false);

  const handleGenerate = async () => {
    if (!files.length) {
      setError("Please upload at least one PDF, image, or PPTX file.");
      return;
    }
    setLoading(true);
    setError(null);
    setDownloadUrl(null);

    const formData = new FormData();
    files.forEach((f) => formData.append("files", f));
    formData.append("num_slides", String(numSlides));

    try {
      const res = await fetch("/api/generate-slides", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Server error ${res.status}`);
      }

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);

      const disposition = res.headers.get("Content-Disposition") || "";
      const match = disposition.match(/filename="?([^"]+)"?/);
      const name = match ? match[1] : "presentation.pptx";

      setDownloadUrl(url);
      setDownloadName(name);
    } catch (err) {
      setError(err.message || "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = () => {
    if (!downloadUrl) return;
    const a = document.createElement("a");
    a.href = downloadUrl;
    a.download = downloadName;
    a.click();
  };

  const formatSize = (bytes) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div className="app">
      {/* Dynamic Animated Blobs */}
      <div className="ambient-bg">
        <div className="blob blob-1"></div>
        <div className="blob blob-2"></div>
        <div className="blob blob-3"></div>
      </div>

      <header className="header">
        <div className="header-inner">
          <div className="logo">
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              style={{ marginRight: "8px" }}
            >
              <polygon points="12 2 2 7 12 12 22 7 12 2" />
              <polyline points="2 17 12 22 22 17" />
              <polyline points="2 12 12 17 22 12" />
            </svg>
            <span>SlideGen AI</span>
          </div>
          <div className="engine-badge">
            <svg
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
            >
              <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
            </svg>
            <span>Claude 4.6 Sonnet Engine</span>
          </div>
        </div>
      </header>

      {/* Hero Section */}
      <section className="hero">
        <span className="badge">Editable PowerPoint Reconstruction</span>
        <h1 className="hero-title">
          Upload visual content, rebuild the text, <br />
          <span className="gradient-text">download editable PPTX</span>
        </h1>
        <p className="hero-subtitle">
          Convert JPG, PNG, PDF, or PPTX files into PowerPoint slides with real
          editable text boxes placed over the original layout.
        </p>
      </section>

      <main className="main">
        {/* Tab Navigation */}
        <div style={styles.tabsContainer}>
          <button
            onClick={() => setActiveTab("edit")}
            style={{
              ...styles.tabButton,
              ...(activeTab === "edit"
                ? styles.tabButtonActive
                : styles.tabButtonInactive),
            }}
          >
            Editable PPTX
          </button>
          <button
            onClick={() => setActiveTab("generate")}
            style={{
              ...styles.tabButton,
              ...(activeTab === "generate"
                ? styles.tabButtonActive
                : styles.tabButtonInactive),
            }}
          >
            Generate PPTX
          </button>
        </div>

        <>
          {/* Edit Content Tab */}
          {activeTab === "edit" && <EditableContent />}

          {/* Generate Slides Tab */}
          {activeTab === "generate" && (
            <>
              <div className="card">
                <h2 className="section-title">
                  <svg
                    width="20"
                    height="20"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <polyline points="17 8 12 3 7 8" />
                    <line x1="12" y1="3" x2="12" y2="15" />
                  </svg>
                  Upload Source Materials
                </h2>

                <div
                  className={`dropzone ${dragging ? "dragging" : ""}`}
                  onDrop={onDrop}
                  onDragOver={onDragOver}
                  onDragLeave={onDragLeave}
                  onClick={() => fileInputRef.current?.click()}
                >
                  {/* Scanner line active during loading or dragging */}
                  {(dragging || loading) && <div className="scan-line"></div>}

                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    accept=".pdf,.pptx,image/*"
                    style={{ display: "none" }}
                    onChange={(e) => addFiles(e.target.files)}
                  />
                  <div className="dropzone-content">
                    <div className="upload-icon">
                      <UploadIcon />
                    </div>
                    <p className="dropzone-primary">
                      Drag & drop your files here or{" "}
                      <span className="link">browse</span>
                    </p>
                    <p className="dropzone-secondary">
                      Supports PDF, PNG, JPG, WEBP, GIF, PPTX
                    </p>
                  </div>
                </div>

                {files.length > 0 && (
                  <ul className="file-list">
                    {files.map((f, i) => (
                      <li key={i} className="file-item">
                        <span className="file-icon">
                          <FileIcon type={f.type} />
                        </span>
                        <div className="file-info">
                          <span className="file-name">{f.name}</span>
                          <span className="file-size">
                            {formatSize(f.size)}
                          </span>
                        </div>
                        <button
                          className="remove-btn"
                          onClick={() => removeFile(i)}
                          title="Remove file"
                        >
                          <svg
                            width="16"
                            height="16"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                          >
                            <line x1="18" y1="6" x2="6" y2="18" />
                            <line x1="6" y1="6" x2="18" y2="18" />
                          </svg>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="card">
                <h2 className="section-title">
                  <svg
                    width="20"
                    height="20"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <circle cx="12" cy="12" r="3" />
                    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
                  </svg>
                  Presentation Settings
                </h2>
                <div className="settings-row">
                  <label className="settings-label">
                    <span>Target slide deck length</span>
                    <span className="slide-count">{numSlides} Slides</span>
                  </label>
                  <div className="slider-wrapper">
                    <input
                      type="range"
                      min="4"
                      max="20"
                      value={numSlides}
                      onChange={(e) => setNumSlides(Number(e.target.value))}
                      className="slider"
                    />
                    <div className="slider-ticks">
                      <span>4 (Brief summary)</span>
                      <span>12 (Standard deck)</span>
                      <span>20 (Deep dive)</span>
                    </div>
                  </div>
                </div>
              </div>

              {error && (
                <div className="error-box">
                  <svg
                    width="18"
                    height="18"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    style={{ marginRight: "6px" }}
                  >
                    <circle cx="12" cy="12" r="10" />
                    <line x1="12" y1="8" x2="12" y2="12" />
                    <line x1="12" y1="16" x2="12.01" y2="16" />
                  </svg>
                  {error}
                </div>
              )}

              <button
                className="generate-btn"
                onClick={handleGenerate}
                disabled={loading || !files.length}
              >
                {loading ? (
                  <>
                    <Spinner />
                    Claude is analyzing content and structuring slides...
                  </>
                ) : (
                  <>
                    <svg
                      width="20"
                      height="20"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2.5"
                      style={{ marginRight: "6px" }}
                    >
                      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                    </svg>
                    Generate PPTX Presentation
                  </>
                )}
              </button>

              {loading && (
                <p className="loading-hint">
                  Anthropic Claude 4.6 Sonnet is extracting core insights,
                  formatting optimal slide layouts (titles, comparisons, double
                  columns), and drafting professional speaker notes. This
                  process usually completes in 15–35 seconds.
                </p>
              )}

              {downloadUrl && (
                <div className="success-box">
                  <div className="success-header">
                    <svg
                      width="22"
                      height="22"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      style={{ marginRight: "6px" }}
                    >
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                    <span>Presentation Compiled Successfully!</span>
                  </div>
                  <button className="download-btn" onClick={handleDownload}>
                    <svg
                      width="18"
                      height="18"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      style={{ marginRight: "6px" }}
                    >
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                      <polyline points="7 10 12 15 17 10" />
                      <line x1="12" y1="15" x2="12" y2="3" />
                    </svg>
                    Download Editable presentation
                  </button>
                </div>
              )}

              {/* Informational AI Features Grid */}
              <section className="features-grid">
                <div className="feature-card">
                  <span className="feature-icon">🧭</span>
                  <h3 className="feature-title">Planning</h3>
                  <p className="feature-desc">
                    Turns uploaded PDFs, images, and decks into a clear slide
                    structure with target length, flow, and source context
                    handled before export.
                  </p>
                </div>
                <div className="feature-card">
                  <span className="feature-icon">🛠️</span>
                  <h3 className="feature-title">Skill</h3>
                  <p className="feature-desc">
                    Reconstructs detected text as real PowerPoint text boxes,
                    preserving the original visual layout while making content
                    editable.
                  </p>
                </div>
                <div className="feature-card">
                  <span className="feature-icon">⚡</span>
                  <h3 className="feature-title">Superpower</h3>
                  <p className="feature-desc">
                    Converts static screenshots, scanned PDFs, and existing
                    PPTX files into downloadable editable presentations in one
                    focused workflow.
                  </p>
                </div>
              </section>
            </>
          )}
        </>
      </main>

      <footer className="footer">
        Powered by Anthropic · Claude 4.6 Sonnet API · Fully responsive layout ·
        Temp files are processed in-memory
      </footer>
    </div>
  );
}

const styles = {
  tabsContainer: {
    display: "flex",
    gap: "16px",
    marginBottom: "24px",
    justifyContent: "center",
    flexWrap: "wrap",
  },
  tabButton: {
    padding: "10px 24px",
    borderRadius: "8px",
    border: "none",
    fontSize: "15px",
    fontWeight: "600",
    cursor: "pointer",
    transition: "all 0.3s",
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  },
  tabButtonActive: {
    background: "linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)",
    color: "white",
    boxShadow: "0 4px 12px rgba(59, 130, 246, 0.4)",
  },
  tabButtonInactive: {
    background: "#f3f4f6",
    color: "#6b7280",
  },
};
