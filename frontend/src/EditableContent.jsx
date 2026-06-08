import { useMemo, useRef, useState } from "react";

const ACCEPTED_FORMATS = [
  "image/png",
  "image/jpeg",
  "image/jpg",
  "application/vnd.ms-powerpoint",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
];

function UploadIcon() {
  return (
    <svg
      width="42"
      height="42"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
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
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
    >
      <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
    >
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  );
}

function isEditableFile(file) {
  if (!file) return false;
  return ACCEPTED_FORMATS.includes(file.type) || file.type.startsWith("image/");
}

function isPowerPoint(file) {
  return (
    file.type.includes("presentationml") ||
    file.type === "application/vnd.ms-powerpoint" ||
    file.name.toLowerCase().endsWith(".ppt") ||
    file.name.toLowerCase().endsWith(".pptx")
  );
}

function getBounds(bbox) {
  const xs = bbox.map((point) => point[0]);
  const ys = bbox.map((point) => point[1]);
  return {
    left: Math.min(...xs),
    top: Math.min(...ys),
    width: Math.max(...xs) - Math.min(...xs),
    height: Math.max(...ys) - Math.min(...ys),
  };
}

function createImageBlocks(textBlocks) {
  return textBlocks.map((block, index) => ({
    ...block,
    id: `block-${index}`,
    text: block.text || "",
    originalText: block.text || "",
    confidence: block.confidence ?? null,
    bbox: block.bbox,
  }));
}

export default function EditableContent() {
  const [step, setStep] = useState("upload");
  const [file, setFile] = useState(null);
  const [fileType, setFileType] = useState(null);
  const [content, setContent] = useState(null);
  const [imageBlocks, setImageBlocks] = useState([]);
  const [slideBlocks, setSlideBlocks] = useState({});
  const [previewUrl, setPreviewUrl] = useState(null);
  const [imageSize, setImageSize] = useState({ width: 1, height: 1 });
  const [selectedBlockId, setSelectedBlockId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const fileInputRef = useRef(null);

  const selectedBlock = useMemo(
    () => imageBlocks.find((block) => block.id === selectedBlockId),
    [imageBlocks, selectedBlockId],
  );

  const handleFile = async (selectedFile) => {
    if (!selectedFile) return;

    if (!isEditableFile(selectedFile)) {
      setError("Only PNG, JPG, or PowerPoint files are supported.");
      return;
    }

    const objectUrl = selectedFile.type.startsWith("image/")
      ? URL.createObjectURL(selectedFile)
      : null;

    if (previewUrl) URL.revokeObjectURL(previewUrl);

    setFile(selectedFile);
    setPreviewUrl(objectUrl);
    setFileType(isPowerPoint(selectedFile) ? "pptx" : "image");
    setContent(null);
    setImageBlocks([]);
    setSlideBlocks({});
    setSelectedBlockId(null);
    setError(null);
    await extractContent(selectedFile);
  };

  const handleFileSelect = (event) => {
    handleFile(event.target.files?.[0]);
  };

  const extractContent = async (selectedFile) => {
    setStep("analyzing");
    setLoading(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append("file", selectedFile);

      const response = await fetch("/api/extract-editable-content", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || "Failed to analyze file.");
      }

      const data = await response.json();
      setFileType(data.file_type);
      setContent(data.content);

      if (data.file_type === "image") {
        const blocks = createImageBlocks(data.content.text_blocks || []);
        setImageBlocks(blocks);
        setSelectedBlockId(blocks[0]?.id || null);
      } else {
        const slides = {};
        data.content.forEach((slide) => {
          slides[slide.slide_number] = (slide.text_blocks || []).map(
            (block, index) => ({
              ...block,
              id: `slide-${slide.slide_number}-shape-${block.shape_index ?? index}`,
              shape_index: block.shape_index,
              text: block.text || "",
              originalText: block.text || "",
            }),
          );
        });
        setSlideBlocks(slides);
      }

      setStep("editing");
    } catch (err) {
      setError(err.message || "Failed to analyze file.");
      setStep("upload");
    } finally {
      setLoading(false);
    }
  };

  const updateBlockText = (blockId, text) => {
    setImageBlocks((blocks) =>
      blocks.map((block) => (block.id === blockId ? { ...block, text } : block)),
    );
  };

  const updateSlideBlockText = (slideNumber, blockId, text) => {
    setSlideBlocks((slides) => ({
      ...slides,
      [slideNumber]: (slides[slideNumber] || []).map((block) =>
        block.id === blockId ? { ...block, text } : block,
      ),
    }));
  };

  const handleSaveContent = async () => {
    if (!file || !fileType) return;

    setLoading(true);
    setError(null);

    try {
      const formData = new FormData();
      const updatedContent =
        fileType === "image" ? { blocks: imageBlocks } : slideBlocks;

      formData.append("file", file);
      formData.append("file_type", fileType);
      formData.append("updated_content", JSON.stringify(updatedContent));

      const response = await fetch("/api/save-edited-content", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || "Failed to save edited file.");
      }

      const blob = await response.blob();
      const downloadUrl = window.URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = downloadUrl;
      anchor.download = file.name;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      window.URL.revokeObjectURL(downloadUrl);
    } catch (err) {
      setError(err.message || "Failed to save edited file.");
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setStep("upload");
    setFile(null);
    setFileType(null);
    setContent(null);
    setImageBlocks([]);
    setSlideBlocks({});
    setPreviewUrl(null);
    setSelectedBlockId(null);
    setError(null);
  };

  const renderImageEditor = () => (
    <div style={styles.workspace}>
      <div style={styles.previewPanel}>
        <div style={styles.imageFrame}>
          {previewUrl && (
            <div style={styles.imageWrap}>
              <img
                src={previewUrl}
                alt={file?.name || "Uploaded image"}
                style={styles.previewImage}
                onLoad={(event) =>
                  setImageSize({
                    width: event.currentTarget.naturalWidth || 1,
                    height: event.currentTarget.naturalHeight || 1,
                  })
                }
              />
              {imageBlocks.map((block) => {
                if (!block.bbox) return null;
                const bounds = getBounds(block.bbox);
                const isSelected = block.id === selectedBlockId;
                return (
                  <button
                    key={block.id}
                    type="button"
                    aria-label={`Edit text block ${block.id}`}
                    onClick={() => setSelectedBlockId(block.id)}
                    style={{
                      ...styles.blockOverlay,
                      left: `${(bounds.left / imageSize.width) * 100}%`,
                      top: `${(bounds.top / imageSize.height) * 100}%`,
                      width: `${(bounds.width / imageSize.width) * 100}%`,
                      height: `${(bounds.height / imageSize.height) * 100}%`,
                      ...(isSelected ? styles.blockOverlaySelected : null),
                    }}
                  />
                );
              })}
            </div>
          )}
        </div>
      </div>

      <div style={styles.editorPanel}>
        <div style={styles.panelHeader}>
          <div>
            <h3 style={styles.sectionTitle}>Editable Text</h3>
            <p style={styles.metaText}>{imageBlocks.length} detected blocks</p>
          </div>
        </div>

        {imageBlocks.length === 0 ? (
          <textarea
            value={content?.full_text || ""}
            readOnly
            style={styles.emptyTextarea}
          />
        ) : (
          <div style={styles.blocksList}>
            {imageBlocks.map((block, index) => (
              <label
                key={block.id}
                style={{
                  ...styles.blockEditor,
                  ...(block.id === selectedBlockId
                    ? styles.blockEditorSelected
                    : null),
                }}
                onClick={() => setSelectedBlockId(block.id)}
              >
                <span style={styles.blockLabel}>Text {index + 1}</span>
                <textarea
                  value={block.text}
                  onChange={(event) =>
                    updateBlockText(block.id, event.target.value)
                  }
                  style={styles.blockTextarea}
                />
              </label>
            ))}
          </div>
        )}

        {selectedBlock && (
          <div style={styles.selectedPreview}>
            <span style={styles.blockLabel}>Original</span>
            <p style={styles.originalText}>{selectedBlock.originalText}</p>
          </div>
        )}
      </div>
    </div>
  );

  const renderPptEditor = () => (
    <div style={styles.pptPanel}>
      <h3 style={styles.sectionTitle}>Editable Slides</h3>
      <div style={styles.slidesContainer}>
        {Array.isArray(content) &&
          content.map((slide) => {
            const blocks = slideBlocks[slide.slide_number] || [];
            return (
              <div key={slide.slide_number} style={styles.slideEditor}>
                <span style={styles.blockLabel}>Slide {slide.slide_number}</span>
                <div style={styles.slideBlocksList}>
                  {blocks.map((block, index) => (
                    <label key={block.id} style={styles.pptBlockEditor}>
                      <span style={styles.shapeLabel}>
                        Text box {index + 1}
                      </span>
                      <textarea
                        value={block.text}
                        onChange={(event) =>
                          updateSlideBlockText(
                            slide.slide_number,
                            block.id,
                            event.target.value,
                          )
                        }
                        style={styles.slideTextarea}
                      />
                    </label>
                  ))}
                </div>
              </div>
            );
          })}
      </div>
    </div>
  );

  return (
    <div style={styles.container}>
      <div style={styles.card}>
        <div style={styles.cardHeader}>
          <div>
            <h2 style={styles.title}>Editable Content Studio</h2>
            <p style={styles.subtitle}>
              Upload, review AI-detected text, edit it, then download the same
              file format.
            </p>
          </div>
          {file && <span style={styles.fileBadge}>{file.name}</span>}
        </div>

        {error && <div style={styles.errorBanner}>{error}</div>}

        {step === "upload" && (
          <div style={styles.uploadSection}>
            <div
              style={styles.uploadArea}
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                handleFile(event.dataTransfer.files?.[0]);
              }}
            >
              <UploadIcon />
              <p style={styles.uploadText}>Upload image or PowerPoint</p>
              <p style={styles.uploadSubtext}>PNG, JPG, PPT, or PPTX</p>
            </div>

            <input
              ref={fileInputRef}
              type="file"
              accept=".jpg,.jpeg,.png,.ppt,.pptx"
              onChange={handleFileSelect}
              style={{ display: "none" }}
            />
          </div>
        )}

        {step === "analyzing" && (
          <div style={styles.loadingState}>
            <Spinner />
            <span>AI is analyzing editable text...</span>
          </div>
        )}

        {step === "editing" && (
          <>
            {fileType === "image" && renderImageEditor()}
            {fileType === "pptx" && renderPptEditor()}

            <div style={styles.buttonGroup}>
              <button
                onClick={handleSaveContent}
                disabled={loading}
                style={{ ...styles.button, ...styles.primaryButton }}
              >
                {loading ? (
                  <>
                    <Spinner /> Saving
                  </>
                ) : (
                  <>
                    <DownloadIcon /> Save & Download
                  </>
                )}
              </button>
              <button
                onClick={handleCancel}
                disabled={loading}
                style={{ ...styles.button, ...styles.secondaryButton }}
              >
                Cancel
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const styles = {
  container: {
    width: "100%",
  },
  card: {
    background: "rgba(13, 17, 28, 0.72)",
    border: "1px solid rgba(255, 255, 255, 0.08)",
    borderRadius: "16px",
    boxShadow: "0 8px 32px rgba(0, 0, 0, 0.24)",
    padding: "28px",
  },
  cardHeader: {
    display: "flex",
    justifyContent: "space-between",
    gap: "16px",
    alignItems: "flex-start",
    marginBottom: "24px",
  },
  title: {
    fontSize: "22px",
    fontWeight: "800",
    margin: 0,
    color: "#ffffff",
  },
  subtitle: {
    margin: "6px 0 0",
    color: "#9ca3af",
    fontSize: "14px",
  },
  fileBadge: {
    maxWidth: "260px",
    padding: "6px 10px",
    borderRadius: "999px",
    color: "#c084fc",
    background: "rgba(139, 92, 246, 0.12)",
    border: "1px solid rgba(139, 92, 246, 0.25)",
    fontSize: "12px",
    fontWeight: "700",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  errorBanner: {
    background: "rgba(239, 68, 68, 0.1)",
    border: "1px solid rgba(239, 68, 68, 0.3)",
    borderRadius: "12px",
    color: "#f87171",
    padding: "12px 14px",
    marginBottom: "18px",
    fontSize: "14px",
  },
  uploadSection: {
    marginTop: "6px",
  },
  uploadArea: {
    border: "2px dashed rgba(255, 255, 255, 0.16)",
    borderRadius: "12px",
    padding: "46px 20px",
    textAlign: "center",
    cursor: "pointer",
    color: "#c084fc",
    background: "rgba(255, 255, 255, 0.02)",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: "10px",
  },
  uploadText: {
    color: "#ffffff",
    margin: 0,
    fontSize: "16px",
    fontWeight: "700",
  },
  uploadSubtext: {
    color: "#9ca3af",
    margin: 0,
    fontSize: "13px",
  },
  loadingState: {
    minHeight: "220px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "10px",
    color: "#e5e7eb",
    fontWeight: "700",
  },
  workspace: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
    gap: "20px",
  },
  previewPanel: {
    minWidth: 0,
  },
  imageFrame: {
    width: "100%",
    minHeight: "380px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    borderRadius: "12px",
    background: "rgba(0, 0, 0, 0.26)",
    border: "1px solid rgba(255, 255, 255, 0.08)",
    overflow: "hidden",
  },
  imageWrap: {
    position: "relative",
    width: "100%",
  },
  previewImage: {
    display: "block",
    width: "100%",
    height: "auto",
  },
  blockOverlay: {
    position: "absolute",
    border: "2px solid rgba(6, 182, 212, 0.9)",
    background: "rgba(6, 182, 212, 0.12)",
    borderRadius: "4px",
    cursor: "pointer",
    padding: 0,
  },
  blockOverlaySelected: {
    borderColor: "#fbbf24",
    background: "rgba(251, 191, 36, 0.22)",
  },
  editorPanel: {
    minWidth: 0,
    borderRadius: "12px",
    background: "rgba(255, 255, 255, 0.03)",
    border: "1px solid rgba(255, 255, 255, 0.08)",
    padding: "16px",
  },
  panelHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: "12px",
  },
  sectionTitle: {
    color: "#ffffff",
    fontSize: "17px",
    margin: 0,
    fontWeight: "800",
  },
  metaText: {
    color: "#9ca3af",
    margin: "4px 0 0",
    fontSize: "12px",
  },
  blocksList: {
    display: "flex",
    flexDirection: "column",
    gap: "12px",
    maxHeight: "430px",
    overflowY: "auto",
    paddingRight: "4px",
  },
  blockEditor: {
    display: "block",
    borderRadius: "10px",
    border: "1px solid rgba(255, 255, 255, 0.08)",
    padding: "10px",
    background: "rgba(255, 255, 255, 0.03)",
    cursor: "pointer",
  },
  blockEditorSelected: {
    borderColor: "rgba(251, 191, 36, 0.65)",
    background: "rgba(251, 191, 36, 0.08)",
  },
  blockLabel: {
    display: "block",
    color: "#c084fc",
    fontSize: "12px",
    fontWeight: "800",
    marginBottom: "6px",
    textTransform: "uppercase",
  },
  blockTextarea: {
    width: "100%",
    minHeight: "70px",
    border: "1px solid rgba(255, 255, 255, 0.1)",
    borderRadius: "8px",
    padding: "9px",
    background: "rgba(7, 9, 14, 0.72)",
    color: "#ffffff",
    resize: "vertical",
    font: "inherit",
    fontSize: "13px",
    lineHeight: 1.45,
  },
  emptyTextarea: {
    width: "100%",
    minHeight: "180px",
    border: "1px solid rgba(255, 255, 255, 0.1)",
    borderRadius: "8px",
    padding: "10px",
    background: "rgba(7, 9, 14, 0.72)",
    color: "#9ca3af",
    resize: "vertical",
  },
  selectedPreview: {
    marginTop: "14px",
    padding: "12px",
    borderRadius: "10px",
    background: "rgba(7, 9, 14, 0.55)",
    border: "1px solid rgba(255, 255, 255, 0.08)",
  },
  originalText: {
    margin: 0,
    color: "#d1d5db",
    fontSize: "13px",
  },
  pptPanel: {
    borderRadius: "12px",
    background: "rgba(255, 255, 255, 0.03)",
    border: "1px solid rgba(255, 255, 255, 0.08)",
    padding: "16px",
  },
  slidesContainer: {
    display: "flex",
    flexDirection: "column",
    gap: "14px",
    maxHeight: "520px",
    overflowY: "auto",
    marginTop: "14px",
  },
  slideEditor: {
    display: "flex",
    flexDirection: "column",
    gap: "10px",
    borderLeft: "4px solid #06b6d4",
    paddingLeft: "12px",
  },
  slideBlocksList: {
    display: "flex",
    flexDirection: "column",
    gap: "10px",
  },
  pptBlockEditor: {
    display: "block",
    padding: "10px",
    borderRadius: "10px",
    border: "1px solid rgba(255, 255, 255, 0.08)",
    background: "rgba(255, 255, 255, 0.03)",
  },
  shapeLabel: {
    display: "block",
    marginBottom: "6px",
    color: "#9ca3af",
    fontSize: "12px",
    fontWeight: "700",
  },
  slideTextarea: {
    width: "100%",
    minHeight: "120px",
    padding: "10px",
    border: "1px solid rgba(255, 255, 255, 0.1)",
    borderRadius: "8px",
    background: "rgba(7, 9, 14, 0.72)",
    color: "#ffffff",
    resize: "vertical",
    font: "inherit",
    fontSize: "13px",
    lineHeight: 1.45,
  },
  buttonGroup: {
    display: "flex",
    gap: "12px",
    marginTop: "22px",
    justifyContent: "flex-end",
    flexWrap: "wrap",
  },
  button: {
    minHeight: "42px",
    padding: "10px 18px",
    borderRadius: "10px",
    border: "none",
    fontSize: "14px",
    fontWeight: "800",
    cursor: "pointer",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "8px",
  },
  primaryButton: {
    background: "linear-gradient(135deg, #10b981 0%, #059669 100%)",
    color: "#ffffff",
  },
  secondaryButton: {
    background: "rgba(255, 255, 255, 0.08)",
    color: "#e5e7eb",
  },
};
