"use client";

import { FlipHorizontal2, FlipVertical2, RotateCcw, RotateCw, Undo2 } from "lucide-react";
import { useEffect, useState } from "react";

import { useDocumentEditor } from "@/editor/EditorState";
import { cropped, flipped, pictureAt, turned, uncropped, updatePicture, withRotation, type CropSide } from "@/editor/pictureEdit";
import type { PictureAttr } from "@/editor/pictureLook";

const inputClass =
  "w-full rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100";
const buttonClass =
  "flex h-8 w-8 items-center justify-center rounded text-zinc-600 transition-colors hover:bg-zinc-100 aria-pressed:bg-accent/10 aria-pressed:text-accent dark:text-zinc-300 dark:hover:bg-zinc-800";
const SIDES: [CropSide, string][] = [
  ["left", "Left"],
  ["right", "Right"],
  ["top", "Top"],
  ["bottom", "Bottom"],
];

const percent = (share: number | undefined) => Math.round((share ?? 0) * 1000) / 10;

/**
 * Crop, turn and flip the selected picture (tracker DOCX-018B): changes to the picture on the
 * page, saved with the document, and both exports draw it so -- a Word export as Word's own
 * crop, turn and flips.
 */
export function PictureControls({ elementId }: { elementId: string }) {
  const { editor } = useDocumentEditor();
  const [picture, setPicture] = useState<PictureAttr | null | undefined>(() => (editor ? pictureAt(editor, elementId) : undefined));

  useEffect(() => {
    if (!editor) return;
    const read = () => setPicture(pictureAt(editor, elementId));
    read();
    editor.on("transaction", read);
    return () => {
      editor.off("transaction", read);
    };
  }, [editor, elementId]);

  if (!editor || picture === undefined) return null;
  const change = (how: (current: PictureAttr | null) => PictureAttr) => updatePicture(editor, elementId, how);
  const crop = picture?.crop;
  const changed = Boolean(crop || picture?.rotation || picture?.flipHorizontal || picture?.flipVertical);

  return (
    <div className="flex flex-col gap-3" aria-label="Crop and turn">
      <div className="flex items-center gap-1" role="group" aria-label="Turn and flip">
        <button type="button" className={buttonClass} aria-label="Turn left" title="Turn left" onClick={() => change((current) => turned(current, -90))}>
          <RotateCcw className="h-4 w-4" aria-hidden="true" />
        </button>
        <button type="button" className={buttonClass} aria-label="Turn right" title="Turn right" onClick={() => change((current) => turned(current, 90))}>
          <RotateCw className="h-4 w-4" aria-hidden="true" />
        </button>
        <button
          type="button"
          className={buttonClass}
          aria-label="Flip across"
          title="Flip across"
          aria-pressed={Boolean(picture?.flipHorizontal)}
          onClick={() => change((current) => flipped(current, "horizontal"))}
        >
          <FlipHorizontal2 className="h-4 w-4" aria-hidden="true" />
        </button>
        <button
          type="button"
          className={buttonClass}
          aria-label="Flip up and down"
          title="Flip up and down"
          aria-pressed={Boolean(picture?.flipVertical)}
          onClick={() => change((current) => flipped(current, "vertical"))}
        >
          <FlipVertical2 className="h-4 w-4" aria-hidden="true" />
        </button>
        <button
          type="button"
          className={`${buttonClass} ml-auto disabled:opacity-40`}
          aria-label="Undo crop and turn"
          title="Back to the picture as it came"
          disabled={!changed}
          onClick={() => change(uncropped)}
        >
          <Undo2 className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <label className="flex flex-col gap-1">
        <span className="text-xs text-zinc-500 dark:text-zinc-400">Turn (°)</span>
        <input
          key={`turn-${picture?.rotation ?? 0}`}
          type="number"
          min={0}
          max={359}
          step={1}
          defaultValue={picture?.rotation ?? 0}
          onBlur={(event) => event.target.value !== "" && change((current) => withRotation(current, Number(event.target.value)))}
          className={inputClass}
        />
      </label>
      <div className="grid grid-cols-2 gap-2" role="group" aria-label="Crop">
        {SIDES.map(([side, label]) => (
          <label key={side} className="flex flex-col gap-1">
            <span className="text-xs text-zinc-500 dark:text-zinc-400">Crop {label.toLowerCase()} (%)</span>
            <input
              key={`${side}-${percent(crop?.[side])}`}
              type="number"
              min={0}
              max={90}
              step={1}
              defaultValue={percent(crop?.[side])}
              onBlur={(event) => event.target.value !== "" && change((current) => cropped(current, side, Number(event.target.value)))}
              className={inputClass}
            />
          </label>
        ))}
      </div>
    </div>
  );
}
