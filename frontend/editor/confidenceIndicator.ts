import { Extension } from "@tiptap/core";

const LOW_CONFIDENCE_THRESHOLD = 0.6;

/**
 * Passive-only confidence marker (no interaction) -- see README for why this
 * phase deliberately stops short of an accept/reject workflow: there is
 * nothing yet for a user to *do* with a flagged element (no reclassify UI,
 * no formatting engine to reconcile a correction into).
 */
export const ConfidenceIndicator = Extension.create({
  name: "confidenceIndicator",
  addGlobalAttributes() {
    return [
      {
        types: ["heading", "paragraph", "blockquote", "codeBlock", "bulletList", "orderedList", "table", "caption"],
        attributes: {
          confidence: {
            default: null,
            renderHTML: (attributes: Record<string, unknown>) => {
              const confidence = attributes.confidence as number | null | undefined;
              if (confidence === null || confidence === undefined) {
                return {};
              }
              const isLow = confidence < LOW_CONFIDENCE_THRESHOLD;
              return {
                "data-confidence": confidence,
                "data-confidence-low": isLow ? "true" : null,
              };
            },
            parseHTML: (element: HTMLElement) => {
              const value = element.getAttribute("data-confidence");
              return value ? Number.parseFloat(value) : null;
            },
          },
        },
      },
    ];
  },
});
