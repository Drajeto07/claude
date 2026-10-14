"use client";

import { Baseline, Highlighter, Image as ImageIcon } from "lucide-react";
import { type KeyboardEvent, type ReactNode } from "react";

import { FONT_FAMILIES, FONT_SIZES } from "@/editor/RichTextToolbar";
import { useI18n } from "@/i18n/I18nProvider";

import { commandsFor, isEnabled, shortcutLabel, type Command, type CommandContext, type CommandGroup } from "./commands";
import type { BlockStyle } from "./selectionModel";

const toolClass = (on: boolean) =>
  `flex h-8 min-w-8 items-center justify-center rounded-lg px-1.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-35 ${
    on ? "bg-accent-soft text-accent" : "text-foreground hover:bg-surface-muted"
  }`;
const selectClass = "h-8 rounded-lg border border-line bg-surface px-1.5 text-sm text-foreground focus:border-accent focus:outline-none";

function Divider() {
  return <span className="mx-0.5 h-6 w-px shrink-0 bg-line" aria-hidden="true" />;
}

function isMac(): boolean {
  return typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
}

/** One registry command as a toolbar button: its label and shortcut from the dictionary and the registry. */
function Tool({ command, context }: { command: Command; context: CommandContext }) {
  const { m } = useI18n();
  const label = m.editorTools.commands[command.id];
  const tip = command.shortcut ? `${label} (${shortcutLabel(command.shortcut, isMac())})` : label;
  const on = command.isActive?.(context) ?? false;
  const Icon = command.icon;
  return (
    <button
      type="button"
      data-tool
      tabIndex={-1}
      aria-label={label}
      title={tip}
      aria-pressed={command.isActive ? on : undefined}
      disabled={!isEnabled(command, context)}
      // The editor keeps its selection: the button doesn't take the focus on press.
      onMouseDown={(event) => event.preventDefault()}
      onClick={() => void command.run(context)}
      className={toolClass(on)}
    >
      <Icon className="h-4 w-4" aria-hidden="true" />
    </button>
  );
}

function Group({ group, context, label }: { group: CommandGroup; context: CommandContext; label: string }) {
  const commands = commandsFor(context.selection.kind, group);
  if (commands.length === 0) return null;
  return (
    <div role="group" aria-label={label} className="flex items-center gap-0.5">
      {commands.map((command) => (
        <Tool key={command.id} command={command} context={context} />
      ))}
    </div>
  );
}

function ColourTool({ label, value, onPick, icon }: { label: string; value: string | null; onPick: (colour: string) => void; icon: ReactNode }) {
  return (
    <label title={label} className={`${toolClass(Boolean(value))} relative cursor-pointer flex-col gap-0.5`}>
      {icon}
      <span className="h-1 w-4 rounded-sm border border-line" style={{ backgroundColor: value ?? "transparent" }} aria-hidden="true" />
      <input
        type="color"
        data-tool
        tabIndex={-1}
        aria-label={label}
        value={value && /^#[0-9a-f]{6}$/i.test(value) ? value : "#000000"}
        onChange={(event) => onPick(event.target.value)}
        className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
      />
    </label>
  );
}

/**
 * The contextual toolbar (E2, architecture §6): above the pages, its tools chosen by what is selected -- text
 * tools for text, the same plus table tools inside a table, picture tools for a picture. Every button is a
 * registry command; arrow keys move between the tools (one tab stop for the whole bar).
 */
export function ContextToolbar({ context }: { context: CommandContext }) {
  const { m } = useI18n();
  const t = m.editorTools;
  const { editor, selection } = context;
  const text = selection.kind === "text" || selection.kind === "table";
  const textStyle = (editor?.getAttributes("textStyle") ?? {}) as { color?: string | null; backgroundColor?: string | null };

  function moveFocus(event: KeyboardEvent<HTMLDivElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    const tools = [...event.currentTarget.querySelectorAll<HTMLElement>("[data-tool]:not(:disabled)")];
    const at = tools.indexOf(document.activeElement as HTMLElement);
    const next = event.key === "Home" ? 0 : event.key === "End" ? tools.length - 1 : (at + (event.key === "ArrowRight" ? 1 : -1) + tools.length) % tools.length;
    tools[next]?.focus();
    event.preventDefault();
  }

  function setBlock(style: BlockStyle) {
    if (!editor) return;
    const chain = editor.chain().focus();
    if (style === "body") chain.setParagraph().run();
    else if (style !== "other") chain.setHeading({ level: Number(style.slice(1)) as 1 | 2 | 3 }).run();
  }

  return (
    <div
      role="toolbar"
      aria-label={t.toolbar}
      onKeyDown={moveFocus}
      // The first tool is the bar's one tab stop.
      onFocus={(event) => {
        if (event.target === event.currentTarget) event.currentTarget.querySelector<HTMLElement>("[data-tool]:not(:disabled)")?.focus();
      }}
      tabIndex={0}
      className="mx-auto flex w-fit max-w-full flex-wrap items-center gap-1 rounded-2xl border border-line bg-surface px-2 py-1.5 shadow-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
    >
      <Group group="history" context={context} label={t.groups.history} />
      <Divider />
      {text && (
        <>
          <div role="group" aria-label={t.groups.text} className="flex flex-wrap items-center gap-1">
            <select
              data-tool
              tabIndex={-1}
              aria-label={t.textStyle}
              title={t.textStyle}
              value={selection.block}
              onChange={(event) => setBlock(event.target.value as BlockStyle)}
              className={selectClass}
            >
              {(["body", "h1", "h2", "h3"] as const).map((style) => (
                <option key={style} value={style}>
                  {t.blockStyles[style]}
                </option>
              ))}
              {selection.block === "other" && <option value="other">{t.blockStyles.other}</option>}
            </select>
            <select
              data-tool
              tabIndex={-1}
              aria-label={t.font}
              title={t.font}
              value=""
              onChange={(event) => event.target.value && editor?.chain().focus().setFontFamily(event.target.value).run()}
              className={`${selectClass} max-w-28`}
            >
              <option value="" disabled>
                {t.font}
              </option>
              {FONT_FAMILIES.map((font) => (
                <option key={font} value={font}>
                  {font}
                </option>
              ))}
            </select>
            <select
              data-tool
              tabIndex={-1}
              aria-label={t.size}
              title={t.size}
              value=""
              onChange={(event) => event.target.value && editor?.chain().focus().setFontSize(event.target.value).run()}
              className={selectClass}
            >
              <option value="" disabled>
                {t.size}
              </option>
              {FONT_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </div>
          <Group group="marks" context={context} label={t.groups.text} />
          <ColourTool label={t.textColour} value={textStyle.color ?? null} onPick={(colour) => editor?.chain().focus().setColor(colour).run()} icon={<Baseline className="h-4 w-4" aria-hidden="true" />} />
          <ColourTool
            label={t.highlight}
            value={textStyle.backgroundColor ?? null}
            onPick={(colour) => editor?.chain().focus().setBackgroundColor(colour).run()}
            icon={<Highlighter className="h-4 w-4" aria-hidden="true" />}
          />
          <Divider />
        </>
      )}
      {selection.kind === "image" && (
        <span className="flex items-center gap-1.5 px-1 text-xs font-medium text-muted">
          <ImageIcon className="h-4 w-4" aria-hidden="true" /> {t.pictureSelected}
        </span>
      )}
      <Group group="align" context={context} label={t.groups.paragraph} />
      {text && <Group group="lists" context={context} label={t.groups.lists} />}
      {selection.kind === "table" && (
        <>
          <Divider />
          <Group group="table" context={context} label={t.groups.table} />
        </>
      )}
      {selection.kind === "image" && (
        <>
          <Divider />
          <Group group="picture" context={context} label={t.groups.picture} />
        </>
      )}
    </div>
  );
}

