"use client";

import type { Ref } from "react";

import { IMAGE_TYPES } from "@/editor/imageFiles";

/**
 * The device's file dialog for pictures (S2-130), hidden: a button opens it (`ref.current.click()`), and the files
 * picked go to `onFiles` -- to the editor engine's insertImageFiles, which checks each by its bytes. One for every
 * place that offers a picture (Add element on larger screens, the 2.0 editor's phone bar), so they behave alike.
 */
export function ImageFileInput({ ref, onFiles, testId = "image-picker" }: { ref: Ref<HTMLInputElement>; onFiles: (files: File[]) => void; testId?: string }) {
  return (
    <input
      ref={ref}
      type="file"
      accept={IMAGE_TYPES.join(",")}
      multiple
      hidden
      data-testid={testId}
      onChange={(event) => {
        const files = Array.from(event.target.files ?? []);
        event.target.value = ""; // the same file can be picked again
        if (files.length) onFiles(files);
      }}
    />
  );
}
